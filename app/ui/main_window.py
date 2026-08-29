from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTableWidgetSelectionRange,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.accuracy.profiles import ACCURACY_PROFILES
from app.core.database import AppDatabase
from app.core.engine import LyricrafterEngine
from app.core.files import discover_audio_files, is_audio_file, next_versioned_path, output_pair_for_audio
from app.core.jobs import AccuracyOptions, JobResult, JobStatus, LyricJob, ProcessingOptions
from app.core.config import default_online_download_dir
from app.core.project import default_project_path, load_project, save_project
from app.core.quality import QualityIssue, check_lyrics_quality, quality_label, quality_score
from app.core.performance import CPU_PERFORMANCE_MODES, cpu_threads_for_mode, logical_cpu_count
from app.core.resources import app_asset_path
from app.core.shell import open_in_file_manager
from app.core.youtube import (
    DEFAULT_FILENAME_TEMPLATE,
    DEFAULT_ONLINE_AUDIO_FORMAT,
    FILENAME_PRESETS,
    SUPPORTED_ONLINE_AUDIO_FORMATS,
    parse_video_urls,
)
from app.export.lrc import (
    LyricLine,
    cleanup_lyric_lines,
    format_lrc_timestamp,
    render_bilingual_lrc,
    render_bilingual_txt,
    render_lrc,
    render_srt,
    render_translated_lrc,
    render_txt,
    render_vtt,
)
from app.export.embed import can_embed_lyrics, embed_lyrics
from app.lyrics.align import align_plain_lyrics
from app.lyrics.parsing import parse_plain_text, parse_plain_text_with_sections
from app.lyrics.service import LyricsSourceService
from app.lyrics.structure import (
    SECTION_KINDS,
    LyricSection,
    SectionOverride,
    SectionRepair,
    detect_lyric_sections,
    repair_repeated_section,
    replace_section_text,
)
from app.lyrics.types import LyricCandidate, ProviderLyrics
from app.models.catalog import ModelCatalog, ModelManager
from app.core.nvidia_runtime import NvidiaRuntimeManager
from app.translation.languages import (
    TRANSLATION_ENGINES,
    language_names,
    model_id_for_engine,
    nllb_code_for_iso,
    nllb_code_for_name,
)
from app.ui.widgets import DropQueueTable, LyricWaveform, LyricrafterMark, SongMap, WaveformWorker
from app.ui.workers import (
    BatchLyricsSourceWorker,
    LyricsSourceWorker,
    MetadataWorker,
    ModelDownloadWorker,
    NvidiaRuntimeWorker,
    ProcessWorker,
    TranslationWorker,
    UrlDownloadWorker,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Lyricrafter")
        self.resize(1280, 780)
        self.setMinimumSize(980, 560)

        self.db = AppDatabase()
        self.online_download_dir = Path(
            self.db.get_setting("online_download_dir") or default_online_download_dir()
        )
        self.online_download_dir.mkdir(parents=True, exist_ok=True)
        self.online_audio_format = self.db.get_setting("online_audio_format", DEFAULT_ONLINE_AUDIO_FORMAT) or DEFAULT_ONLINE_AUDIO_FORMAT
        self.online_filename_template = self.db.get_setting("online_filename_template", DEFAULT_FILENAME_TEMPLATE) or DEFAULT_FILENAME_TEMPLATE
        self.accuracy_preset = self.db.get_setting("accuracy_preset", "balanced") or "balanced"
        self.accuracy_user_hints = self.db.get_setting("accuracy_user_hints", "") or ""
        self.accuracy_use_metadata = _setting_bool(self.db.get_setting("accuracy_use_metadata", "true"), True)
        self.accuracy_two_pass = _setting_bool(self.db.get_setting("accuracy_two_pass", "false"), False)
        self.accuracy_lock_language = _setting_bool(self.db.get_setting("accuracy_lock_language", "true"), True)
        self.accuracy_condition_previous = _setting_bool(self.db.get_setting("accuracy_condition_previous", "false"), False)
        self.source_lrclib_enabled = _setting_bool(self.db.get_setting("source_lrclib", "true"), True)
        self.source_local_enabled = _setting_bool(self.db.get_setting("source_local", "true"), True)
        self.source_captions_enabled = _setting_bool(self.db.get_setting("source_captions", "true"), True)
        self.source_synced_enabled = _setting_bool(self.db.get_setting("source_synced", "true"), True)
        self.source_experimental_enabled = _setting_bool(self.db.get_setting("source_experimental", "false"), False)
        self.export_lrc_enabled = _setting_bool(self.db.get_setting("export_lrc", "true"), True)
        self.export_txt_enabled = _setting_bool(self.db.get_setting("export_txt", "true"), True)
        self.export_srt_enabled = _setting_bool(self.db.get_setting("export_srt", "false"), False)
        self.export_vtt_enabled = _setting_bool(self.db.get_setting("export_vtt", "false"), False)
        self.logical_cpu_threads = logical_cpu_count()
        saved_cpu_mode = self.db.get_setting("cpu_performance_mode", "auto") or "auto"
        self.cpu_performance_mode = saved_cpu_mode if saved_cpu_mode in CPU_PERFORMANCE_MODES else "auto"
        try:
            saved_custom_threads = int(self.db.get_setting("cpu_custom_threads", "0") or 0)
        except ValueError:
            saved_custom_threads = 0
        self.cpu_custom_threads = cpu_threads_for_mode(
            "custom",
            saved_custom_threads or cpu_threads_for_mode("auto", logical_threads=self.logical_cpu_threads),
            self.logical_cpu_threads,
        )
        self.catalog = ModelCatalog()
        self.model_manager = ModelManager()
        self.engine = LyricrafterEngine(model_manager=self.model_manager)
        self.jobs: list[LyricJob] = []
        self.process_worker: ProcessWorker | None = None
        self.download_worker: ModelDownloadWorker | None = None
        self.nvidia_runtime_manager = NvidiaRuntimeManager()
        self.nvidia_runtime_worker: NvidiaRuntimeWorker | None = None
        self.url_download_worker: UrlDownloadWorker | None = None
        self.metadata_worker: MetadataWorker | None = None
        self.translation_worker: TranslationWorker | None = None
        self.waveform_workers: list[WaveformWorker] = []
        self.lyrics_source_worker: LyricsSourceWorker | None = None
        self.batch_lyrics_source_worker: BatchLyricsSourceWorker | None = None
        self.lyrics_source_dialog: LyricsSourcesDialog | None = None
        self.batch_lyrics_dialog: BatchLyricsSourcesDialog | None = None
        self.lyrics_source_job: LyricJob | None = None
        self.pending_provider_apply: tuple[str, ProviderLyrics, float] | None = None
        self.pending_provider_applies: dict[str, tuple[ProviderLyrics, float]] = {}
        self.batch_source_matches: dict[str, list[LyricCandidate]] = {}
        self.current_editor_job: LyricJob | None = None
        self._seeking_slider = False
        self._current_sync_row = -1
        self._syncing_table_selection = False
        self._editor_updating = False
        self._undo_stack: list[list[LyricLine]] = []
        self._redo_stack: list[list[LyricLine]] = []
        self._last_editor_lines: list[LyricLine] = []
        self._waveform_drag_snapshot: list[LyricLine] | None = None
        self._song_sections: list[LyricSection] = []
        self._section_overrides: list[SectionOverride] = []
        self._section_master: LyricSection | None = None
        self._section_loop_bounds: tuple[float, float] | None = None
        self._loop_seek_active = False
        self._pending_missing_lines: list[tuple[str, float]] = []
        self._structure_refresh_timer = QTimer(self)
        self._structure_refresh_timer.setSingleShot(True)
        self._structure_refresh_timer.setInterval(180)
        self._structure_refresh_timer.timeout.connect(self._refresh_song_structure)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player.setAudioOutput(self.audio_output)

        central = QWidget()
        central.setObjectName("ApplicationShell")
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        central_layout.addWidget(self.sidebar)
        self.tabs = QStackedWidget()
        self.tabs.setObjectName("WorkspaceStack")
        central_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self._build_queue_tab()
        self._build_editor_tab()
        self._build_models_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self._set_workspace_page(0)
        self._build_menu()
        self.statusBar().showMessage("Ready")
        self._load_settings()
        self._refresh_model_table()
        self._refresh_history()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact_height = self.height() < 680
        if hasattr(self, "editor_preview_panel"):
            self.editor_preview_panel.setVisible(not compact_height)
        if hasattr(self, "timeline_help"):
            self.timeline_help.setVisible(not compact_height and self.width() >= 1180)

        if hasattr(self, "sidebar"):
            compact_width = self.width() < 1120
            self.sidebar.setFixedWidth(184 if compact_width else 204)
            if hasattr(self, "brand_subtitle"):
                self.brand_subtitle.setVisible(not compact_width)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(204)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)

        brand = QWidget()
        brand.setObjectName("SidebarBrand")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(2, 0, 2, 14)
        brand_layout.setSpacing(10)
        brand_layout.addWidget(LyricrafterMark())
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("Lyricrafter")
        title.setObjectName("SidebarTitle")
        self.brand_subtitle = QLabel("STUDIO")
        self.brand_subtitle.setObjectName("SidebarSubtitle")
        brand_text.addWidget(title)
        brand_text.addWidget(self.brand_subtitle)
        brand_layout.addLayout(brand_text, 1)
        layout.addWidget(brand)

        workspace_label = QLabel("WORKSPACE")
        workspace_label.setObjectName("NavSectionLabel")
        layout.addWidget(workspace_label)
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(3)
        layout.addLayout(self.nav_layout)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        layout.addStretch(1)

        engine_label = QLabel("LOCAL AI ENGINE")
        engine_label.setObjectName("NavSectionLabel")
        layout.addWidget(engine_label)
        self.header_status = QLabel("Ready")
        self.header_status.setObjectName("SidebarStatus")
        self.header_status.setWordWrap(True)
        self.header_status.setMaximumHeight(84)
        layout.addWidget(self.header_status)
        return sidebar

    def _add_workspace_page(
        self,
        page: QWidget,
        label: str,
        icon: QStyle.StandardPixmap,
        asset_name: str,
    ) -> None:
        index = self.tabs.addWidget(page)
        button = QPushButton(label)
        button.setObjectName("NavigationButton")
        button.setCheckable(True)
        asset_icon = QIcon(str(app_asset_path(f"icons/{asset_name}")))
        button.setIcon(asset_icon if not asset_icon.isNull() else self.style().standardIcon(icon))
        button.setIconSize(QSize(19, 19))
        button.setShortcut(f"Ctrl+{index + 1}")
        button.setToolTip(f"Open {label} (Ctrl+{index + 1})")
        button.clicked.connect(lambda _checked=False, page_index=index: self._set_workspace_page(page_index))
        self.nav_group.addButton(button, index)
        self.nav_buttons.append(button)
        self.nav_layout.addWidget(button)

    def _set_workspace_page(self, index: int) -> None:
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)

    def _build_menu(self) -> None:
        self.menuBar().hide()
        file_menu = self.menuBar().addMenu("&File")
        add_files = QAction("Add audio files", self)
        add_files.triggered.connect(self.add_files)
        file_menu.addAction(add_files)
        add_folder = QAction("Add folder", self)
        add_folder.triggered.connect(self.add_folder)
        file_menu.addAction(add_folder)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_queue_tab(self) -> None:
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)

        hero_widget = QWidget()
        hero_widget.setMaximumHeight(52)
        hero = QHBoxLayout(hero_widget)
        hero.setContentsMargins(0, 0, 0, 0)
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("Production Queue")
        title.setObjectName("HeroTitle")
        subtitle = QLabel("Add tracks, choose a model, and generate synced lyrics beside each audio file.")
        subtitle.setObjectName("Muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        hero.addLayout(title_block, 1)
        self.stat_queued_value = self._make_stat_card(hero, "Queued", "0")
        self.stat_done_value = self._make_stat_card(hero, "Complete", "0")
        self.stat_failed_value = self._make_stat_card(hero, "Failed", "0")
        self.stat_progress_value = self._make_stat_card(hero, "Batch", "0%")
        root.addWidget(hero_widget)

        actions_widget = QWidget()
        actions_widget.setObjectName("CommandBar")
        actions_widget.setMaximumHeight(52)
        top_actions = QHBoxLayout(actions_widget)
        top_actions.setContentsMargins(8, 7, 8, 7)
        add_files_btn = self._queue_icon_button(
            "Add Files",
            asset_hint="file_plus",
            fallback=QStyle.SP_FileIcon,
            primary=True,
        )
        add_files_btn.clicked.connect(self.add_files)
        add_folder_btn = self._queue_icon_button("Add Folder", asset_hint="folder_plus", fallback=QStyle.SP_DirOpenIcon)
        add_folder_btn.clicked.connect(self.add_folder)
        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setToolTip("Include audio inside nested folders when adding or dropping a folder.")
        self.start_btn = self._queue_icon_button(
            "Start Queue",
            asset_hint="play",
            fallback=QStyle.SP_MediaPlay,
            primary=True,
        )
        self.start_btn.clicked.connect(self.start_queue)
        self.cancel_btn = self._queue_icon_button(
            "Cancel",
            asset_hint="cancel",
            fallback=QStyle.SP_BrowserStop,
            danger=True,
        )
        self.cancel_btn.clicked.connect(self.cancel_queue)
        self.cancel_btn.setEnabled(False)
        retry_btn = self._queue_icon_button("Retry Failed", asset_hint="replay", fallback=QStyle.SP_BrowserReload)
        retry_btn.clicked.connect(self.retry_failed)
        open_editor_btn = self._queue_icon_button("Open in Editor", asset_hint="edit", fallback=QStyle.SP_FileDialogDetailedView)
        open_editor_btn.clicked.connect(self.open_selected_job_in_editor)
        find_lyrics_btn = self._queue_icon_button(
            "Find Lyrics",
            asset_hint="search",
            fallback=QStyle.SP_FileDialogContentsView,
        )
        find_lyrics_btn.clicked.connect(self.find_lyrics_for_selected_job)
        batch_lyrics_btn = self._queue_icon_button(
            "Batch Sources",
            asset_hint="batch",
            fallback=QStyle.SP_FileDialogContentsView,
        )
        batch_lyrics_btn.clicked.connect(self.batch_find_lyrics_sources)
        regen_btn = self._queue_icon_button("Regenerate", asset_hint="reboot", fallback=QStyle.SP_BrowserReload)
        regen_btn.clicked.connect(self.regenerate_selected_jobs)
        remove_btn = self._queue_icon_button("Remove Selected", asset_hint="remove", fallback=QStyle.SP_TrashIcon)
        remove_btn.clicked.connect(self.remove_selected_jobs)
        clear_btn = self._queue_icon_button("Clear Queue", asset_hint="remove", fallback=QStyle.SP_TrashIcon, danger=True)
        clear_btn.clicked.connect(self.clear_queue)
        top_actions.addWidget(add_files_btn)
        top_actions.addWidget(add_folder_btn)
        top_actions.addWidget(self.recursive_check)
        top_actions.addStretch(1)
        top_actions.addWidget(open_editor_btn)
        top_actions.addWidget(find_lyrics_btn)
        top_actions.addWidget(batch_lyrics_btn)
        top_actions.addWidget(regen_btn)
        top_actions.addWidget(remove_btn)
        top_actions.addWidget(clear_btn)
        top_actions.addWidget(retry_btn)
        top_actions.addWidget(self.cancel_btn)
        top_actions.addWidget(self.start_btn)
        root.addWidget(actions_widget)

        root.addWidget(self._build_online_sources_panel())

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        center = QWidget()
        center.setObjectName("WorkSurface")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(14, 14, 14, 14)
        queue_header = QHBoxLayout()
        queue_title = QLabel("Tracks")
        queue_title.setObjectName("PanelTitle")
        self.queue_filter_edit = QLineEdit()
        self.queue_filter_edit.setObjectName("CompactSearch")
        self.queue_filter_edit.setPlaceholderText("Filter tracks")
        self.queue_filter_edit.setClearButtonEnabled(True)
        self.queue_filter_edit.setMaximumWidth(220)
        self.queue_filter_edit.textChanged.connect(self._filter_queue_rows)
        queue_header.addWidget(queue_title)
        queue_header.addStretch(1)
        queue_header.addWidget(self.queue_filter_edit)
        center_layout.addLayout(queue_header)
        self.queue_table = DropQueueTable(0, 5)
        self.queue_table.paths_dropped.connect(self.add_dropped_sources)
        self.queue_table.setHorizontalHeaderLabels(["Track", "Status", "Progress", "Activity", "Outputs"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.queue_table.verticalHeader().hide()
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setShowGrid(False)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self.show_queue_context_menu)
        center_layout.addWidget(self.queue_table, 1)

        right = QWidget()
        right.setObjectName("InspectorSurface")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(12)
        settings = QGroupBox("Processing")
        self.processing_group = settings
        settings.setMinimumHeight(330)
        settings.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        form = QFormLayout(settings)
        form.setContentsMargins(14, 18, 14, 14)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.model_combo = QComboBox()
        for model in self.catalog.list_models("whisper"):
            label = f"{model.name} ({model.id})"
            if model.id == "large-v2":
                label = f"{label} - Default"
            self.model_combo.addItem(label, model.id)
        self.preset_combo = QComboBox()
        for profile in ACCURACY_PROFILES:
            self.preset_combo.addItem(profile.name, profile.id)
        profile_index = self.preset_combo.findData(self.accuracy_preset)
        if profile_index >= 0:
            self.preset_combo.setCurrentIndex(profile_index)
        accuracy_advanced_btn = QPushButton("Advanced Accuracy")
        accuracy_advanced_btn.clicked.connect(self.open_accuracy_dialog)
        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cpu", "cuda"])
        self.device_combo.setToolTip("Use auto unless CUDA is fully installed. CPU is slower but reliable.")
        self.compute_combo = QComboBox()
        self.compute_combo.addItems(["auto", "float16", "float32", "int8_float16", "int8_float32", "int8"])
        self.compute_combo.setToolTip(
            "Auto preserves quality with float16 on CUDA and float32 on CPU. "
            "INT8 modes use less memory but can reduce recognition accuracy on difficult vocals."
        )
        self.language_combo = QComboBox()
        self.language_combo.addItem("Auto detect", None)
        for code in ["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"]:
            self.language_combo.addItem(code, code)
        self.vad_check = QCheckBox("Voice detection")
        self.vad_check.setChecked(False)
        self.vad_check.setToolTip("Off by default for music because speech VAD can cut sung vocals.")
        self.vocal_check = QCheckBox("Vocal isolation")
        self.vocal_check.setToolTip("Accuracy presets can also enable this automatically for cleaner lyric detection.")
        self.version_check = QCheckBox("Version outputs")
        self.version_check.setChecked(True)
        self.embed_check = QCheckBox("Embed lyrics")
        self.embed_check.setToolTip("Writes lyrics tags into supported audio files. Sidecar files follow the selected output formats.")
        self.export_lrc_check = QCheckBox("LRC")
        self.export_txt_check = QCheckBox("TXT")
        self.export_srt_check = QCheckBox("SRT")
        self.export_vtt_check = QCheckBox("VTT")
        self.export_lrc_check.setChecked(self.export_lrc_enabled)
        self.export_txt_check.setChecked(self.export_txt_enabled)
        self.export_srt_check.setChecked(self.export_srt_enabled)
        self.export_vtt_check.setChecked(self.export_vtt_enabled)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        for checkbox in (self.export_lrc_check, self.export_txt_check, self.export_srt_check, self.export_vtt_check):
            checkbox.stateChanged.connect(self._save_output_settings)
            output_row.addWidget(checkbox)
        output_row.addStretch(1)
        output_widget = QWidget()
        output_widget.setLayout(output_row)
        self.separation_combo = QComboBox()
        for model in self.catalog.list_models("separation"):
            self.separation_combo.addItem(model.name, model.id)
        for combo in (
            self.model_combo,
            self.preset_combo,
            self.language_combo,
            self.separation_combo,
            self.device_combo,
            self.compute_combo,
        ):
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        form.addRow("Whisper model", self.model_combo)
        form.addRow("Accuracy preset", self.preset_combo)
        form.addRow("Language", self.language_combo)
        output_block = QWidget()
        output_block_layout = QVBoxLayout(output_block)
        output_block_layout.setContentsMargins(0, 4, 0, 0)
        output_block_layout.setSpacing(6)
        output_label = QLabel("OUTPUTS")
        output_label.setObjectName("SectionLabel")
        output_block_layout.addWidget(output_label)
        output_block_layout.addWidget(output_widget)
        output_block_layout.addWidget(self.embed_check)
        form.addRow(output_block)

        self.processing_advanced_toggle = QToolButton()
        self.processing_advanced_toggle.setObjectName("DisclosureButton")
        self.processing_advanced_toggle.setText("Advanced settings")
        self.processing_advanced_toggle.setCheckable(True)
        self.processing_advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.processing_advanced_toggle.toggled.connect(self._toggle_processing_advanced)
        self.processing_advanced_panel = QWidget()
        advanced_form = QFormLayout(self.processing_advanced_panel)
        advanced_form.setContentsMargins(0, 4, 0, 0)
        advanced_form.setVerticalSpacing(9)
        advanced_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        advanced_form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        advanced_form.addRow(accuracy_advanced_btn)
        advanced_form.addRow("Device", self.device_combo)
        advanced_form.addRow("Compute", self.compute_combo)
        advanced_form.addRow(self.vad_check)
        advanced_form.addRow(self.vocal_check)
        advanced_form.addRow("Separation", self.separation_combo)
        advanced_form.addRow(self.version_check)
        form.addRow(self.processing_advanced_toggle)
        form.addRow(self.processing_advanced_panel)
        advanced_open = _setting_bool(self.db.get_setting("processing_advanced_open", "false"), False)
        self.processing_advanced_toggle.setChecked(advanced_open)
        self._toggle_processing_advanced(advanced_open)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setFrameStyle(0)
        settings_scroll.setWidget(settings)
        right_layout.addWidget(settings_scroll, 1)
        right.setMinimumWidth(370)

        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([880, 390])
        self._add_workspace_page(tab, "Queue", QStyle.SP_FileDialogListView, "list_8800.svg")

    def _filter_queue_rows(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.queue_table.rowCount()):
            values: list[str] = []
            for column in (0, 1, 3, 4):
                item = self.queue_table.item(row, column)
                if item is not None:
                    values.append(item.text())
            haystack = " ".join(values).casefold()
            self.queue_table.setRowHidden(row, bool(needle) and needle not in haystack)

    def _toggle_processing_advanced(self, expanded: bool) -> None:
        self.processing_advanced_panel.setVisible(expanded)
        if hasattr(self, "processing_group"):
            self.processing_group.setMinimumHeight(470 if expanded else 250)
        icon = QStyle.SP_ArrowUp if expanded else QStyle.SP_ArrowDown
        self.processing_advanced_toggle.setIcon(self.style().standardIcon(icon))
        self.processing_advanced_toggle.setToolTip("Hide advanced processing" if expanded else "Show advanced processing")
        self.db.set_setting("processing_advanced_open", str(expanded).lower())

    def _build_online_sources_panel(self) -> QWidget:
        url_widget = QWidget()
        url_widget.setObjectName("OnlinePanel")
        url_layout = QVBoxLayout(url_widget)
        url_layout.setContentsMargins(14, 12, 14, 12)
        url_layout.setSpacing(8)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        title = QLabel("Online Sources")
        title.setObjectName("PanelTitle")
        subtitle = QLabel("Download audio to a visible folder, then add it to the queue.")
        subtitle.setObjectName("Muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)
        self.online_sources_toggle = QToolButton()
        self.online_sources_toggle.setObjectName("CompactToolButton")
        self.online_sources_toggle.setToolTip("Collapse online import")
        self.online_sources_toggle.clicked.connect(self._toggle_online_sources)
        header.addWidget(self.online_sources_toggle)
        url_layout.addLayout(header)

        self.online_sources_content = QWidget()
        content_layout = QVBoxLayout(self.online_sources_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.url_input = QLineEdit()
        self.url_input.setObjectName("UrlInput")
        self.url_input.setPlaceholderText("Paste one or more YouTube, YouTube Music, Vimeo, or SoundCloud URLs")
        self.url_input.setFixedHeight(38)
        self.url_input.returnPressed.connect(self.download_url_to_queue)
        self.url_download_btn = self._queue_icon_button(
            "Download URL Audio",
            asset_hint="download",
            fallback=QStyle.SP_ArrowDown,
            primary=True,
        )
        self.url_download_btn.clicked.connect(self.download_url_to_queue)
        input_row.addWidget(self.url_input, 1)
        input_row.addWidget(self.url_download_btn)
        content_layout.addLayout(input_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        format_label = QLabel("Format")
        format_label.setObjectName("Muted")
        self.online_format_combo = QComboBox()
        self.online_format_combo.addItems([item.upper() for item in SUPPORTED_ONLINE_AUDIO_FORMATS])
        format_index = self.online_format_combo.findText(self.online_audio_format.upper())
        if format_index >= 0:
            self.online_format_combo.setCurrentIndex(format_index)
        self.online_format_combo.currentTextChanged.connect(self._save_online_download_settings)
        preset_label = QLabel("Filename")
        preset_label.setObjectName("Muted")
        self.filename_preset_combo = QComboBox()
        for name, template in FILENAME_PRESETS.items():
            self.filename_preset_combo.addItem(name, template)
        preset_index = self.filename_preset_combo.findData(self.online_filename_template)
        if preset_index < 0:
            preset_index = 0
            self.online_filename_template = DEFAULT_FILENAME_TEMPLATE
        self.filename_preset_combo.setCurrentIndex(preset_index)
        self.filename_preset_combo.currentIndexChanged.connect(self._save_online_download_settings)
        options_row.addWidget(format_label)
        options_row.addWidget(self.online_format_combo)
        options_row.addWidget(preset_label)
        options_row.addWidget(self.filename_preset_combo, 1)
        content_layout.addLayout(options_row)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        save_label = QLabel("Save audio to")
        save_label.setObjectName("Muted")
        self.url_folder_label = QLabel(str(self.online_download_dir))
        self.url_folder_label.setObjectName("PathLabel")
        self.url_folder_label.setToolTip(str(self.online_download_dir))
        choose_folder_btn = self._queue_icon_button(
            "Choose Download Folder",
            asset_hint="folder_plus",
            fallback=QStyle.SP_DirOpenIcon,
        )
        choose_folder_btn.clicked.connect(self.choose_online_download_dir)
        open_folder_btn = self._queue_icon_button("Open Download Folder", fallback=QStyle.SP_DirIcon)
        open_folder_btn.clicked.connect(self.open_online_download_dir)
        folder_row.addWidget(save_label)
        folder_row.addWidget(self.url_folder_label, 1)
        folder_row.addWidget(choose_folder_btn)
        folder_row.addWidget(open_folder_btn)
        content_layout.addLayout(folder_row)
        url_layout.addWidget(self.online_sources_content)
        expanded = _setting_bool(self.db.get_setting("online_sources_expanded_v2", "false"), False)
        self.online_sources_content.setVisible(expanded)
        self._refresh_online_sources_toggle(expanded)
        return url_widget

    def _toggle_online_sources(self) -> None:
        expanded = not self.online_sources_content.isVisible()
        self.online_sources_content.setVisible(expanded)
        self.db.set_setting("online_sources_expanded_v2", str(expanded).lower())
        self._refresh_online_sources_toggle(expanded)

    def _refresh_online_sources_toggle(self, expanded: bool) -> None:
        icon = QStyle.SP_ArrowUp if expanded else QStyle.SP_ArrowDown
        self.online_sources_toggle.setIcon(self.style().standardIcon(icon))
        self.online_sources_toggle.setToolTip("Collapse online import" if expanded else "Expand online import")

    def _queue_icon_button(
        self,
        tooltip: str,
        asset_hint: str | None = None,
        fallback: QStyle.StandardPixmap | None = None,
        primary: bool = False,
        danger: bool = False,
    ) -> QPushButton:
        button = QPushButton("")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setProperty("iconOnly", True)
        button.setFixedSize(38, 36)
        button.setIconSize(QSize(20, 20))
        if primary:
            button.setObjectName("PrimaryButton")
        elif danger:
            button.setObjectName("DangerButton")
        icon = self._asset_icon(asset_hint) if asset_hint else QIcon()
        if icon.isNull() and fallback is not None:
            icon = self.style().standardIcon(fallback)
        button.setIcon(icon)
        return button

    def _asset_icon(self, hint: str | None) -> QIcon:
        if not hint:
            return QIcon()
        icon_dir = Path(__file__).resolve().parents[1] / "assets" / "icons"
        matches = sorted(icon_dir.glob(f"*{hint}*.svg"))
        return QIcon(str(matches[0])) if matches else QIcon()

    def _make_stat_card(self, parent_layout: QHBoxLayout, label: str, value: str) -> QLabel:
        card = QWidget()
        card.setObjectName("StatChip")
        card.setMinimumSize(96, 36)
        card.setMaximumHeight(38)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(11, 5, 11, 5)
        layout.setSpacing(7)
        value_label = QLabel(value)
        value_label.setObjectName("StatValue")
        label_widget = QLabel(label)
        label_widget.setObjectName("StatLabel")
        layout.addWidget(value_label)
        layout.addWidget(label_widget, 1)
        parent_layout.addWidget(card)
        return value_label

    def _build_editor_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        header = QWidget()
        header.setObjectName("Panel")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(8)
        title_row = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        self.editor_title = QLabel("No completed job loaded")
        self.editor_title.setObjectName("PanelTitle")
        self.now_playing_label = QLabel("Generate or select a completed job to review synchronization.")
        self.now_playing_label.setObjectName("Muted")
        title_block.addWidget(self.editor_title)
        title_block.addWidget(self.now_playing_label)
        title_row.addLayout(title_block, 1)
        mode_badge = QLabel("LINE SYNC")
        mode_badge.setObjectName("ModeBadge")
        title_row.addWidget(mode_badge)
        header_layout.addLayout(title_row)

        self.editor_preview_panel = QWidget()
        self.editor_preview_panel.setObjectName("PreviewPanel")
        preview_layout = QVBoxLayout(self.editor_preview_panel)
        preview_layout.setContentsMargins(18, 10, 18, 10)
        preview_layout.setSpacing(3)
        self.preview_original_label = QLabel("No lyric loaded")
        self.preview_original_label.setObjectName("LyricPreview")
        self.preview_original_label.setWordWrap(True)
        self.preview_translation_label = QLabel("")
        self.preview_translation_label.setObjectName("TranslationPreview")
        self.preview_translation_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_original_label)
        preview_layout.addWidget(self.preview_translation_label)
        header_layout.addWidget(self.editor_preview_panel)

        structure_header = QHBoxLayout()
        structure_title = QLabel("SONG MAP")
        structure_title.setObjectName("SectionLabel")
        self.section_detect_label = QLabel("Structure appears after lyrics are loaded")
        self.section_detect_label.setObjectName("Muted")
        detect_structure_btn = QToolButton()
        detect_structure_btn.setObjectName("CompactToolButton")
        detect_structure_btn.setText("Detect")
        detect_structure_btn.setToolTip("Rebuild verse, chorus, bridge, and outro sections")
        detect_structure_btn.clicked.connect(self.redetect_song_structure)
        structure_header.addWidget(structure_title)
        structure_header.addWidget(self.section_detect_label)
        structure_header.addStretch(1)
        structure_header.addWidget(detect_structure_btn)
        header_layout.addLayout(structure_header)
        self.song_map = SongMap()
        self.song_map.section_selected.connect(self._select_song_section)
        header_layout.addWidget(self.song_map)

        timeline_header = QHBoxLayout()
        timeline_title = QLabel("TIMING TIMELINE")
        timeline_title.setObjectName("SectionLabel")
        self.timeline_help = QLabel("Drag a marker to retime a line. Ctrl+wheel zooms; wheel pans.")
        self.timeline_help.setObjectName("Muted")
        timeline_header.addWidget(timeline_title)
        timeline_header.addWidget(self.timeline_help)
        timeline_header.addStretch(1)
        zoom_out_btn = QToolButton()
        zoom_out_btn.setObjectName("CompactToolButton")
        zoom_out_btn.setText("-")
        zoom_out_btn.setToolTip("Zoom out waveform")
        zoom_in_btn = QToolButton()
        zoom_in_btn.setObjectName("CompactToolButton")
        zoom_in_btn.setText("+")
        zoom_in_btn.setToolTip("Zoom in waveform")
        zoom_fit_btn = QToolButton()
        zoom_fit_btn.setObjectName("CompactToolButton")
        zoom_fit_btn.setText("Fit")
        zoom_fit_btn.setToolTip("Show the entire track")
        timeline_header.addWidget(zoom_out_btn)
        timeline_header.addWidget(zoom_in_btn)
        timeline_header.addWidget(zoom_fit_btn)
        header_layout.addLayout(timeline_header)

        self.waveform = LyricWaveform()
        self.waveform.seek_requested.connect(lambda seconds: self.player.setPosition(int(seconds * 1000)))
        self.waveform.line_selected.connect(self._select_waveform_line)
        self.waveform.timing_drag_started.connect(self._begin_waveform_timing_drag)
        self.waveform.timing_changed.connect(self._apply_waveform_timing)
        zoom_out_btn.clicked.connect(self.waveform.zoom_out)
        zoom_in_btn.clicked.connect(self.waveform.zoom_in)
        zoom_fit_btn.clicked.connect(self.waveform.fit)
        header_layout.addWidget(self.waveform)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        self.seek_back_btn = self._make_transport_button(QStyle.SP_MediaSeekBackward, "Back 5s")
        self.seek_back_btn.clicked.connect(lambda: self.seek_relative(-5000))
        self.play_btn = self._make_transport_button(QStyle.SP_MediaPlay, "Play")
        self.play_btn.clicked.connect(self.play_current_audio)
        self.pause_btn = self._make_transport_button(QStyle.SP_MediaPause, "Pause")
        self.pause_btn.clicked.connect(self.player.pause)
        self.stop_btn = self._make_transport_button(QStyle.SP_MediaStop, "Stop")
        self.stop_btn.clicked.connect(self.player.stop)
        self.seek_forward_btn = self._make_transport_button(QStyle.SP_MediaSeekForward, "Forward 5s")
        self.seek_forward_btn.clicked.connect(lambda: self.seek_relative(5000))
        self.current_time_label = QLabel("00:00.00")
        self.current_time_label.setObjectName("Muted")
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.sliderPressed.connect(self._begin_slider_seek)
        self.timeline_slider.sliderReleased.connect(self._commit_slider_seek)
        self.timeline_slider.sliderMoved.connect(self._preview_slider_seek)
        self.duration_label = QLabel("00:00.00")
        self.duration_label.setObjectName("Muted")
        self.undo_btn = self._make_transport_button(QStyle.SP_ArrowBack, "Undo last editor change (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo_editor_edit)
        self.redo_btn = self._make_transport_button(QStyle.SP_ArrowForward, "Redo last editor change (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo_editor_edit)
        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)
        transport.addWidget(self.seek_back_btn)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.pause_btn)
        transport.addWidget(self.stop_btn)
        transport.addWidget(self.seek_forward_btn)
        transport.addSpacing(4)
        transport.addWidget(self.undo_btn)
        transport.addWidget(self.redo_btn)
        transport.addWidget(self.current_time_label)
        transport.addWidget(self.timeline_slider, 1)
        transport.addWidget(self.duration_label)
        nudge_back = QPushButton("-0.10s")
        nudge_back.clicked.connect(lambda: self.nudge_selected_lines(-0.10))
        nudge_forward = QPushButton("+0.10s")
        nudge_forward.clicked.connect(lambda: self.nudge_selected_lines(0.10))
        split_btn = QPushButton("Split")
        split_btn.clicked.connect(self.split_selected_line)
        merge_btn = QPushButton("Merge")
        merge_btn.clicked.connect(self.merge_selected_lines)
        embed_btn = QPushButton("Embed Lyrics")
        embed_btn.clicked.connect(self.embed_current_editor_lyrics)
        save_btn = QPushButton("Save Edited Files")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self.save_editor_outputs)
        header_layout.addLayout(transport)
        layout.addWidget(header)
        self.player.positionChanged.connect(self._sync_player_position)
        self.player.durationChanged.connect(self._sync_player_duration)

        split = QSplitter(Qt.Horizontal)
        split.setObjectName("Panel")
        self.lyric_table = QTableWidget(0, 2)
        self.lyric_table.setColumnCount(3)
        self.lyric_table.setHorizontalHeaderLabels(["Start", "Original", "Translation"])
        self.lyric_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.lyric_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.lyric_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lyric_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lyric_table.verticalHeader().hide()
        self.lyric_table.setAlternatingRowColors(True)
        self.lyric_table.setShowGrid(False)
        self.lyric_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lyric_table.customContextMenuRequested.connect(self.show_editor_context_menu)
        self.lyric_table.itemSelectionChanged.connect(self._seek_to_selected_lyric)
        self.lyric_table.cellClicked.connect(self._seek_to_clicked_lyric)
        self.lyric_table.itemChanged.connect(self._on_editor_item_changed)
        self.lyric_table.setColumnHidden(2, True)
        self.editor_text = QTextEdit(tab)
        self.editor_text.hide()
        split.addWidget(self.lyric_table)
        options_panel = self._build_editor_options_panel(
            nudge_back,
            nudge_forward,
            split_btn,
            merge_btn,
            embed_btn,
            save_btn,
        )
        split.addWidget(options_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([940, 330])
        layout.addWidget(split, 1)

        undo_action = QAction("Undo lyric edit", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo_editor_edit)
        self.addAction(undo_action)
        redo_action = QAction("Redo lyric edit", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self.redo_editor_edit)
        self.addAction(redo_action)
        stamp_action = QAction("Stamp lyric and select next", self)
        stamp_action.setShortcut("F8")
        stamp_action.triggered.connect(self.stamp_selected_line_and_advance)
        self.addAction(stamp_action)
        self._add_workspace_page(tab, "Editor", QStyle.SP_FileDialogDetailedView, "editor_qwy6uhbxcr1i.svg")

    def _build_editor_options_panel(self, *edit_buttons: QPushButton) -> QWidget:
        nudge_back, nudge_forward, split_btn, merge_btn, embed_btn, save_btn = edit_buttons
        inspector = QTabWidget()
        inspector.setObjectName("InspectorTabs")
        inspector.setMinimumWidth(286)
        inspector.setMaximumWidth(370)
        inspector.tabBar().setUsesScrollButtons(False)
        inspector.tabBar().setExpanding(True)

        project = QWidget()
        project_layout = QVBoxLayout(project)
        project_layout.setContentsMargins(12, 14, 12, 12)
        project_layout.setSpacing(9)
        project_intro = QLabel("LYRIC PROJECT")
        project_intro.setObjectName("SectionLabel")
        save_project_btn = QPushButton("Save Project")
        save_project_btn.clicked.connect(self.save_editor_project)
        open_project_btn = QPushButton("Open Project")
        open_project_btn.clicked.connect(self.open_project_file)
        find_lyrics_btn = QPushButton("Find Lyrics")
        find_lyrics_btn.setObjectName("PrimaryButton")
        find_lyrics_btn.clicked.connect(self.find_lyrics_for_editor_job)
        project_layout.addWidget(project_intro)
        project_layout.addWidget(find_lyrics_btn)
        project_layout.addWidget(save_project_btn)
        project_layout.addWidget(open_project_btn)
        project_layout.addSpacing(8)
        export_intro = QLabel("OUTPUT")
        export_intro.setObjectName("SectionLabel")
        project_layout.addWidget(export_intro)
        project_layout.addWidget(embed_btn)
        project_layout.addWidget(save_btn)
        project_layout.addStretch(1)
        project_tab = inspector.addTab(self._inspector_scroll(project), "File")
        inspector.setTabToolTip(project_tab, "Project files and lyric outputs")

        timing_content = QWidget()
        timing_layout = QVBoxLayout(timing_content)
        timing_layout.setContentsMargins(12, 14, 12, 12)
        timing_layout.setSpacing(9)
        quick_label = QLabel("QUICK TIMING")
        quick_label.setObjectName("SectionLabel")
        timing_layout.addWidget(quick_label)
        nudge_row = QHBoxLayout()
        nudge_row.addWidget(nudge_back)
        nudge_row.addWidget(nudge_forward)
        timing_layout.addLayout(nudge_row)
        split_row = QHBoxLayout()
        split_row.addWidget(split_btn)
        split_row.addWidget(merge_btn)
        timing_layout.addLayout(split_row)
        self.shift_amount_spin = QDoubleSpinBox()
        self.shift_amount_spin.setRange(-30.0, 30.0)
        self.shift_amount_spin.setDecimals(2)
        self.shift_amount_spin.setSingleStep(0.05)
        self.shift_amount_spin.setSuffix(" s")
        self.shift_amount_spin.setValue(0.25)
        shift_btn = QPushButton("Shift Selected")
        shift_btn.clicked.connect(self.shift_selected_by_amount)
        set_playhead_btn = QPushButton("Set Start to Playhead")
        set_playhead_btn.clicked.connect(self.set_selected_start_to_playhead)
        stamp_next_btn = QPushButton("Stamp && Next   F8")
        stamp_next_btn.setObjectName("PrimaryButton")
        stamp_next_btn.setToolTip("Set this line to the playhead and select the next line without stopping playback.")
        stamp_next_btn.clicked.connect(self.stamp_selected_line_and_advance)
        sort_btn = QPushButton("Sort by Time")
        sort_btn.clicked.connect(self.sort_editor_lines_by_time)
        space_btn = QPushButton("Space Selected")
        space_btn.setToolTip("Evenly space selected lyric lines between the first and last timestamp.")
        space_btn.clicked.connect(self.space_selected_lines)
        timing_layout.addWidget(self.shift_amount_spin)
        timing_layout.addWidget(shift_btn)
        timing_layout.addWidget(set_playhead_btn)
        timing_layout.addWidget(stamp_next_btn)
        timing_layout.addWidget(space_btn)
        timing_layout.addWidget(sort_btn)
        timing_layout.addSpacing(8)
        cleanup_label = QLabel("TEXT REPAIR")
        cleanup_label.setObjectName("SectionLabel")
        cleanup_btn = QPushButton("Clean Lyric Lines")
        cleanup_btn.clicked.connect(self.cleanup_editor_lines)
        merge_short_btn = QPushButton("Merge Short Fragments")
        merge_short_btn.setToolTip("Merge very short lyric fragments into nearby lines when timing is close.")
        merge_short_btn.clicked.connect(self.merge_short_editor_lines)
        timing_layout.addWidget(cleanup_label)
        timing_layout.addWidget(cleanup_btn)
        timing_layout.addWidget(merge_short_btn)
        timing_layout.addStretch(1)
        timing_tab = inspector.addTab(self._inspector_scroll(timing_content), "Time")
        inspector.setTabToolTip(timing_tab, "Timing and text repair tools")

        sections_content = QWidget()
        sections_layout = QVBoxLayout(sections_content)
        sections_layout.setContentsMargins(12, 14, 12, 12)
        sections_layout.setSpacing(8)
        sections_title = QLabel("SECTION INTELLIGENCE")
        sections_title.setObjectName("SectionLabel")
        self.section_summary_label = QLabel("Load lyrics to detect song sections.")
        self.section_summary_label.setObjectName("Muted")
        self.section_summary_label.setWordWrap(True)
        self.section_list = QListWidget()
        self.section_list.setObjectName("SectionList")
        self.section_list.setMinimumHeight(138)
        self.section_list.itemClicked.connect(self._select_section_list_item)
        detect_sections_btn = QPushButton("Detect Structure")
        detect_sections_btn.clicked.connect(self.redetect_song_structure)
        merge_previous_btn = QPushButton("Merge Previous")
        merge_previous_btn.setToolTip("Combine the selected section with the section immediately before it.")
        merge_previous_btn.clicked.connect(lambda: self.merge_selected_section_with_neighbor(-1))
        merge_next_btn = QPushButton("Merge Next")
        merge_next_btn.setToolTip("Combine the selected section with the section immediately after it.")
        merge_next_btn.clicked.connect(lambda: self.merge_selected_section_with_neighbor(1))
        merge_section_row = QHBoxLayout()
        merge_section_row.addWidget(merge_previous_btn)
        merge_section_row.addWidget(merge_next_btn)
        next_repeat_btn = QPushButton("Next Match")
        next_repeat_btn.setToolTip("Jump to the next occurrence of this repeated section.")
        next_repeat_btn.clicked.connect(self.select_next_matching_section)
        self.section_master_label = QLabel("Master: none")
        self.section_master_label.setObjectName("Muted")
        use_master_btn = QPushButton("Use as Master")
        use_master_btn.setToolTip("Use the selected section as the trusted text for another repeated section.")
        use_master_btn.clicked.connect(self.use_selected_section_as_master)
        repair_section_btn = QPushButton("Repair from Master")
        repair_section_btn.setObjectName("PrimaryButton")
        repair_section_btn.setToolTip("Replace the selected section text while preserving its destination timing.")
        repair_section_btn.clicked.connect(self.repair_selected_section_from_master)
        repair_all_btn = QPushButton("Repair All Repeats")
        repair_all_btn.setToolTip("Apply the master text to every matching repeated section while keeping local timing.")
        repair_all_btn.clicked.connect(self.repair_all_repeats_from_master)
        self.section_repair_quality_label = QLabel("Select a master and destination to preview repair quality.")
        self.section_repair_quality_label.setObjectName("Muted")
        self.section_repair_quality_label.setWordWrap(True)
        self.section_loop_btn = QPushButton("Loop Section")
        self.section_loop_btn.setCheckable(True)
        self.section_loop_btn.setToolTip("Continuously replay the selected song section for synchronization review.")
        self.section_loop_btn.toggled.connect(self.toggle_selected_section_loop)
        copy_section_btn = QPushButton("Copy Text")
        copy_section_btn.clicked.connect(self.copy_selected_section_text)
        paste_section_btn = QPushButton("Paste, Keep Timing")
        paste_section_btn.clicked.connect(self.paste_text_into_selected_section)
        clipboard_row = QHBoxLayout()
        clipboard_row.addWidget(copy_section_btn)
        clipboard_row.addWidget(paste_section_btn)
        self.missing_line_label = QLabel("UNMATCHED MASTER LINES")
        self.missing_line_label.setObjectName("SectionLabel")
        self.missing_line_combo = QComboBox()
        self.missing_line_combo.setToolTip("Master lines that could not be mapped to an existing destination timestamp.")
        self.place_missing_suggested_btn = QPushButton("Place Suggested")
        self.place_missing_suggested_btn.setToolTip(
            "Insert the selected line at a time inferred from nearby AI-timed destination lines."
        )
        self.place_missing_suggested_btn.clicked.connect(self.place_missing_line_at_suggested_time)
        self.place_missing_playhead_btn = QPushButton("Place at Playhead")
        self.place_missing_playhead_btn.setToolTip("Insert the selected unmatched line at the current audio position.")
        self.place_missing_playhead_btn.clicked.connect(self.place_missing_line_at_playhead)
        missing_row = QHBoxLayout()
        missing_row.addWidget(self.place_missing_suggested_btn)
        missing_row.addWidget(self.place_missing_playhead_btn)
        for widget in (
            self.missing_line_label,
            self.missing_line_combo,
            self.place_missing_suggested_btn,
            self.place_missing_playhead_btn,
        ):
            widget.setVisible(False)
        mark_label = QLabel("MANUAL LABEL")
        mark_label.setObjectName("SectionLabel")
        self.section_kind_combo = QComboBox()
        self.section_kind_combo.addItems(SECTION_KINDS)
        mark_section_btn = QPushButton("Mark Selected Lines")
        mark_section_btn.clicked.connect(self.mark_selected_lines_as_section)
        clear_marks_btn = QPushButton("Clear Manual Labels")
        clear_marks_btn.clicked.connect(self.clear_manual_section_labels)
        sections_layout.addWidget(sections_title)
        sections_layout.addWidget(self.section_summary_label)
        sections_layout.addWidget(self.section_list)
        sections_layout.addWidget(detect_sections_btn)
        sections_layout.addLayout(merge_section_row)
        sections_layout.addWidget(next_repeat_btn)
        sections_layout.addWidget(self.section_master_label)
        sections_layout.addWidget(use_master_btn)
        sections_layout.addWidget(repair_section_btn)
        sections_layout.addWidget(repair_all_btn)
        sections_layout.addWidget(self.section_repair_quality_label)
        sections_layout.addWidget(self.section_loop_btn)
        sections_layout.addLayout(clipboard_row)
        sections_layout.addWidget(self.missing_line_label)
        sections_layout.addWidget(self.missing_line_combo)
        sections_layout.addLayout(missing_row)
        sections_layout.addSpacing(6)
        sections_layout.addWidget(mark_label)
        sections_layout.addWidget(self.section_kind_combo)
        sections_layout.addWidget(mark_section_btn)
        sections_layout.addWidget(clear_marks_btn)
        sections_layout.addStretch(1)
        sections_tab = inspector.addTab(self._inspector_scroll(sections_content), "Song")
        inspector.setTabToolTip(sections_tab, "Song sections and repeated-section repair")

        translation = QWidget()
        translation_layout = QVBoxLayout(translation)
        translation_layout.setContentsMargins(12, 14, 12, 12)
        translation_layout.setSpacing(8)
        translation_intro = QLabel("LOCAL TRANSLATION")
        translation_intro.setObjectName("SectionLabel")
        self.translation_engine_combo = QComboBox()
        self.translation_engine_combo.addItems(TRANSLATION_ENGINES)
        self.source_language_combo = QComboBox()
        self.source_language_combo.addItems(language_names(include_auto=True))
        self.target_language_combo = QComboBox()
        self.target_language_combo.addItems(language_names(include_auto=False))
        translate_btn = QPushButton("Translate Lines")
        translate_btn.setObjectName("PrimaryButton")
        translate_btn.clicked.connect(self.translate_lines_placeholder)
        translation_layout.addWidget(translation_intro)
        translation_layout.addWidget(QLabel("Engine"))
        translation_layout.addWidget(self.translation_engine_combo)
        translation_layout.addWidget(QLabel("Source"))
        translation_layout.addWidget(self.source_language_combo)
        translation_layout.addWidget(QLabel("Target"))
        translation_layout.addWidget(self.target_language_combo)
        translation_layout.addWidget(translate_btn)
        translation_layout.addSpacing(8)
        display_title = QLabel("DISPLAY")
        display_title.setObjectName("SectionLabel")
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItems(["Original + Translation", "Original Only", "Translation Only"])
        self.display_mode_combo.currentTextChanged.connect(self._refresh_preview_mode)
        translation_layout.addWidget(display_title)
        translation_layout.addWidget(self.display_mode_combo)
        translation_layout.addStretch(1)
        translation_tab = inspector.addTab(self._inspector_scroll(translation), "Lang")
        inspector.setTabToolTip(translation_tab, "Translation and bilingual display")

        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(12, 14, 12, 12)
        review_layout.setSpacing(9)
        score_row = QHBoxLayout()
        score_title = QLabel("SYNC QUALITY")
        score_title.setObjectName("SectionLabel")
        self.quality_score_label = QLabel("--")
        self.quality_score_label.setObjectName("QualityScore")
        score_row.addWidget(score_title)
        score_row.addStretch(1)
        score_row.addWidget(self.quality_score_label)
        quality_btn = QPushButton("Analyze Lyrics")
        quality_btn.setObjectName("PrimaryButton")
        quality_btn.clicked.connect(self.run_quality_check)
        self.quality_list = QListWidget()
        self.quality_list.setObjectName("QualityList")
        self.quality_list.setWordWrap(True)
        self.quality_list.itemClicked.connect(self._activate_quality_item)
        review_layout.addLayout(score_row)
        review_layout.addWidget(quality_btn)
        review_layout.addWidget(self.quality_list, 1)
        review_tab = inspector.addTab(self._inspector_scroll(review), "Check")
        inspector.setTabToolTip(review_tab, "Quality checks and review warnings")
        return inspector

    def _inspector_scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _make_transport_button(self, icon: QStyle.StandardPixmap, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("TransportButton")
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setFixedSize(36, 34)
        return button

    def _add_page_heading(
        self,
        layout: QVBoxLayout,
        title: str,
        subtitle: str,
        badge: str | None = None,
    ) -> None:
        heading = QHBoxLayout()
        heading.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        text.addWidget(title_label)
        text.addWidget(subtitle_label)
        heading.addLayout(text, 1)
        if badge:
            badge_label = QLabel(badge)
            badge_label.setObjectName("ModeBadge")
            heading.addWidget(badge_label, 0, Qt.AlignTop)
        layout.addLayout(heading)

    def _build_models_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        self._add_page_heading(
            layout,
            "Model Library",
            "Manage local transcription and separation models.",
            "LOCAL MODELS",
        )
        self.model_table = QTableWidget(0, 7)
        self.model_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Best For", "Family", "Backend", "Size", "Status"]
        )
        self.model_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.model_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.model_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.model_table, 1)
        download_group = QGroupBox("Download Status")
        download_layout = QVBoxLayout(download_group)
        self.model_download_label = QLabel("No active model download")
        self.model_download_label.setObjectName("Muted")
        self.model_download_progress = QProgressBar()
        self.model_download_progress.setRange(0, 100)
        self.model_download_progress.setValue(0)
        download_layout.addWidget(self.model_download_label)
        download_layout.addWidget(self.model_download_progress)
        layout.addWidget(download_group)
        gpu_group = QGroupBox("NVIDIA Acceleration")
        gpu_layout = QVBoxLayout(gpu_group)
        self.nvidia_runtime_label = QLabel(self.nvidia_runtime_manager.status_text())
        self.nvidia_runtime_label.setObjectName("Muted")
        self.nvidia_runtime_label.setWordWrap(True)
        self.nvidia_runtime_progress = QProgressBar()
        self.nvidia_runtime_progress.setRange(0, 100)
        self.nvidia_runtime_progress.setValue(100 if self.nvidia_runtime_manager.installed else 0)
        gpu_actions = QHBoxLayout()
        self.install_nvidia_btn = QPushButton("Install NVIDIA Support")
        self.install_nvidia_btn.setToolTip(
            "Downloads the optional NVIDIA CUDA libraries for faster-whisper. "
            "Translation and vocal isolation continue to use CPU in the compact Windows build."
        )
        self.install_nvidia_btn.clicked.connect(self.install_nvidia_runtime)
        self.remove_nvidia_btn = QPushButton("Remove NVIDIA Support")
        self.remove_nvidia_btn.setObjectName("DangerButton")
        self.remove_nvidia_btn.clicked.connect(self.remove_nvidia_runtime)
        gpu_actions.addWidget(self.install_nvidia_btn)
        gpu_actions.addWidget(self.remove_nvidia_btn)
        gpu_actions.addStretch(1)
        gpu_layout.addWidget(self.nvidia_runtime_label)
        gpu_layout.addWidget(self.nvidia_runtime_progress)
        gpu_layout.addLayout(gpu_actions)
        layout.addWidget(gpu_group)
        self._refresh_nvidia_runtime_controls()
        actions = QHBoxLayout()
        download_btn = QPushButton("Download Selected")
        download_btn.setObjectName("PrimaryButton")
        download_btn.clicked.connect(self.download_selected_model)
        download_all_btn = QPushButton("Download All Faster-Whisper")
        download_all_btn.clicked.connect(self.download_all_faster_whisper)
        delete_model_btn = QPushButton("Delete Selected")
        delete_model_btn.setObjectName("DangerButton")
        delete_model_btn.clicked.connect(self.delete_selected_model)
        open_models_btn = QPushButton("Open Model Folder")
        open_models_btn.clicked.connect(self.open_model_folder)
        actions.addWidget(download_btn)
        actions.addWidget(download_all_btn)
        actions.addWidget(delete_model_btn)
        actions.addWidget(open_models_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._add_workspace_page(tab, "Models", QStyle.SP_DriveHDIcon, "models_q48f9jpnpu0e.svg")

    def _build_history_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        self._add_page_heading(
            layout,
            "Activity History",
            "Review completed, failed, and exported lyric jobs.",
        )
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Updated", "Source", "Status", "Message", "Outputs"])
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.history_table, 1)
        actions = QHBoxLayout()
        refresh_btn = QPushButton("Refresh History")
        refresh_btn.clicked.connect(self._refresh_history)
        clear_history_btn = QPushButton("Clear History")
        clear_history_btn.setObjectName("DangerButton")
        clear_history_btn.clicked.connect(self.clear_history)
        actions.addWidget(refresh_btn)
        actions.addWidget(clear_history_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._add_workspace_page(tab, "History", QStyle.SP_BrowserReload, "history_10058.svg")

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        self._add_page_heading(
            layout,
            "Preferences",
            "Configure storage, online imports, lyric sources, and export formats.",
        )
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("SettingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setFrameStyle(0)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 2, 8, 4)
        body_layout.setSpacing(12)
        defaults = QGroupBox("Defaults")
        form = QFormLayout(defaults)
        self.model_dir_label = QLabel(str(self.model_manager.model_dir))
        choose_model_dir = QPushButton("Choose Model Folder")
        choose_model_dir.clicked.connect(self.choose_model_dir)
        self.online_dir_label = QLabel(str(self.online_download_dir))
        choose_online_dir = QPushButton("Choose Online Download Folder")
        choose_online_dir.clicked.connect(self.choose_online_download_dir)
        open_online_dir = QPushButton("Open Online Download Folder")
        open_online_dir.clicked.connect(self.open_online_download_dir)
        self.settings_online_format_combo = QComboBox()
        self.settings_online_format_combo.addItems([item.upper() for item in SUPPORTED_ONLINE_AUDIO_FORMATS])
        settings_format_index = self.settings_online_format_combo.findText(self.online_audio_format.upper())
        if settings_format_index >= 0:
            self.settings_online_format_combo.setCurrentIndex(settings_format_index)
        self.settings_online_format_combo.currentTextChanged.connect(self._sync_settings_online_format)
        self.settings_filename_preset_combo = QComboBox()
        for name, template in FILENAME_PRESETS.items():
            self.settings_filename_preset_combo.addItem(name, template)
        settings_preset_index = self.settings_filename_preset_combo.findData(self.online_filename_template)
        if settings_preset_index < 0:
            settings_preset_index = 0
        self.settings_filename_preset_combo.setCurrentIndex(settings_preset_index)
        self.settings_filename_preset_combo.currentIndexChanged.connect(self._sync_settings_filename_preset)
        form.addRow("Model storage", self.model_dir_label)
        form.addRow("", choose_model_dir)
        form.addRow("Online downloads", self.online_dir_label)
        form.addRow("", choose_online_dir)
        form.addRow("", open_online_dir)
        form.addRow("Online audio format", self.settings_online_format_combo)
        form.addRow("Online filename", self.settings_filename_preset_combo)
        body_layout.addWidget(defaults)
        body_layout.addWidget(self._build_cpu_performance_group())
        sources = QGroupBox("Sources")
        sources_layout = QHBoxLayout(sources)
        self.settings_lrclib_check = QCheckBox("LRCLIB")
        self.settings_lrclib_check.setToolTip("Free synced/plain lyrics source. Used only when Find Lyrics is opened.")
        self.settings_lrclib_check.setChecked(self.source_lrclib_enabled)
        self.settings_local_check = QCheckBox("Local")
        self.settings_local_check.setToolTip("Read nearby .lrc/.txt files and embedded lyrics.")
        self.settings_local_check.setChecked(self.source_local_enabled)
        self.settings_captions_check = QCheckBox("Captions")
        self.settings_captions_check.setToolTip("Read nearby .srt/.vtt caption files.")
        self.settings_captions_check.setChecked(self.source_captions_enabled)
        self.settings_synced_check = QCheckBox("Synced")
        self.settings_synced_check.setToolTip("Search syncedlyrics providers including NetEase, Megalobiz, Musixmatch, and Genius plain lyrics.")
        self.settings_synced_check.setChecked(self.source_synced_enabled)
        self.settings_experimental_check = QCheckBox("Exp.")
        self.settings_experimental_check.setToolTip("Reserved for experimental providers. Off by default.")
        self.settings_experimental_check.setChecked(self.source_experimental_enabled)
        for checkbox in (
            self.settings_lrclib_check,
            self.settings_local_check,
            self.settings_captions_check,
            self.settings_synced_check,
            self.settings_experimental_check,
        ):
            checkbox.stateChanged.connect(self._save_source_settings)
            sources_layout.addWidget(checkbox)
        sources_layout.addStretch(1)
        body_layout.addWidget(sources)
        outputs = QGroupBox("Outputs")
        outputs_layout = QHBoxLayout(outputs)
        self.settings_export_lrc_check = QCheckBox("LRC")
        self.settings_export_txt_check = QCheckBox("TXT")
        self.settings_export_srt_check = QCheckBox("SRT")
        self.settings_export_vtt_check = QCheckBox("VTT")
        self.settings_export_lrc_check.setToolTip("Standard synced lyric file.")
        self.settings_export_txt_check.setToolTip("Plain lyric text file.")
        self.settings_export_srt_check.setToolTip("Subtitle-style export generated from lyric line timing.")
        self.settings_export_vtt_check.setToolTip("WebVTT export generated from lyric line timing.")
        self.settings_export_lrc_check.setChecked(self.export_lrc_enabled)
        self.settings_export_txt_check.setChecked(self.export_txt_enabled)
        self.settings_export_srt_check.setChecked(self.export_srt_enabled)
        self.settings_export_vtt_check.setChecked(self.export_vtt_enabled)
        for checkbox in (
            self.settings_export_lrc_check,
            self.settings_export_txt_check,
            self.settings_export_srt_check,
            self.settings_export_vtt_check,
        ):
            checkbox.stateChanged.connect(self._save_output_settings)
            outputs_layout.addWidget(checkbox)
        outputs_layout.addStretch(1)
        body_layout.addWidget(outputs)
        body_layout.addStretch(1)
        self.settings_scroll.setWidget(body)
        layout.addWidget(self.settings_scroll, 1)
        self._add_workspace_page(tab, "Settings", QStyle.SP_FileDialogContentsView, "settings_59996.svg")

    def _build_cpu_performance_group(self) -> QGroupBox:
        group = QGroupBox("CPU Performance")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        hardware = QLabel(f"Detected {self.logical_cpu_threads} logical processors")
        hardware.setObjectName("Muted")
        hardware.setToolTip("These controls affect faster-whisper transcription on CPU and CUDA fallback.")
        layout.addWidget(hardware)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self.cpu_mode_group = QButtonGroup(self)
        self.cpu_mode_group.setExclusive(True)
        self.cpu_mode_buttons: dict[str, QPushButton] = {}
        mode_definitions = (
            ("auto", "Auto", "Recommended balance of transcription speed and system responsiveness."),
            ("background", "Background", "Lower CPU usage while you continue using the computer."),
            ("balanced", "Balanced", "Moderate CPU usage with additional headroom for other applications."),
            ("maximum", "Maximum", "Use every logical processor. This produces the most heat and may not scale linearly."),
            ("custom", "Custom", "Choose an exact faster-whisper CPU thread count."),
        )
        for index, (mode, label, tooltip) in enumerate(mode_definitions):
            button = QPushButton(label)
            button.setObjectName("PerformanceModeButton")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda checked=False, selected=mode: self._set_cpu_performance_mode(selected) if checked else None
            )
            self.cpu_mode_group.addButton(button, index)
            self.cpu_mode_buttons[mode] = button
            mode_row.addWidget(button)
        layout.addLayout(mode_row)

        thread_row = QHBoxLayout()
        thread_row.setSpacing(10)
        thread_label = QLabel("CPU threads")
        thread_label.setMinimumWidth(82)
        self.cpu_thread_slider = QSlider(Qt.Horizontal)
        self.cpu_thread_slider.setRange(1, self.logical_cpu_threads)
        self.cpu_thread_slider.setSingleStep(1)
        self.cpu_thread_slider.setPageStep(max(1, self.logical_cpu_threads // 10))
        self.cpu_thread_slider.valueChanged.connect(self._set_cpu_custom_threads)
        self.cpu_thread_value = QLabel()
        self.cpu_thread_value.setObjectName("ThreadValue")
        self.cpu_thread_value.setMinimumWidth(112)
        self.cpu_thread_value.setAlignment(Qt.AlignCenter)
        thread_row.addWidget(thread_label)
        thread_row.addWidget(self.cpu_thread_slider, 1)
        thread_row.addWidget(self.cpu_thread_value)
        layout.addLayout(thread_row)

        self.cpu_performance_note = QLabel()
        self.cpu_performance_note.setObjectName("Muted")
        self.cpu_performance_note.setWordWrap(True)
        layout.addWidget(self.cpu_performance_note)

        selected_button = self.cpu_mode_buttons[self.cpu_performance_mode]
        selected_button.setChecked(True)
        self._refresh_cpu_performance_controls()
        return group

    def _set_cpu_performance_mode(self, mode: str) -> None:
        if mode not in CPU_PERFORMANCE_MODES:
            return
        self.cpu_performance_mode = mode
        self.db.set_setting("cpu_performance_mode", mode)
        self._refresh_cpu_performance_controls()

    def _set_cpu_custom_threads(self, value: int) -> None:
        if self.cpu_performance_mode != "custom":
            return
        self.cpu_custom_threads = max(1, min(self.logical_cpu_threads, value))
        self.db.set_setting("cpu_custom_threads", str(self.cpu_custom_threads))
        self._refresh_cpu_performance_controls()

    def _selected_cpu_threads(self) -> int:
        return cpu_threads_for_mode(
            self.cpu_performance_mode,
            self.cpu_custom_threads,
            self.logical_cpu_threads,
        )

    def _refresh_cpu_performance_controls(self) -> None:
        threads = self._selected_cpu_threads()
        custom = self.cpu_performance_mode == "custom"
        self.cpu_thread_slider.blockSignals(True)
        self.cpu_thread_slider.setValue(threads)
        self.cpu_thread_slider.blockSignals(False)
        self.cpu_thread_slider.setEnabled(custom)
        self.cpu_thread_value.setText(f"{threads} / {self.logical_cpu_threads}")
        notes = {
            "auto": f"Recommended: Whisper will use {threads} threads and leave capacity for the interface and audio tools.",
            "background": f"Whisper will use {threads} threads to keep the system responsive during long batches.",
            "balanced": f"Whisper will use {threads} threads for moderate speed and multitasking headroom.",
            "maximum": f"Whisper will use all {threads} logical processors. Expect higher power use, heat, and fan noise.",
            "custom": f"Whisper will use exactly {threads} threads. Changes apply when the next model job starts.",
        }
        self.cpu_performance_note.setText(notes[self.cpu_performance_mode])

    def _load_settings(self) -> None:
        model_dir = self.db.get_setting("model_dir")
        if model_dir:
            self.model_manager = ModelManager(Path(model_dir))
            self.engine.set_model_manager(self.model_manager)
            self.model_dir_label.setText(str(self.model_manager.model_dir))
        model_id = self.db.get_setting("model_id", "large-v2")
        index = self.model_combo.findData(model_id)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        preset = self.db.get_setting("accuracy_preset", self.accuracy_preset) or self.accuracy_preset
        preset_index = self.preset_combo.findData(preset)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        saved_device = self.db.get_setting("device", "auto") or "auto"
        if saved_device == "cuda" and not _cuda_available():
            saved_device = "auto"
            self.header_status.setText("CUDA unavailable; using CPU fallback")
            self.statusBar().showMessage("CUDA unavailable; using CPU fallback")
        self.device_combo.setCurrentText(saved_device)

    def _save_settings(self) -> None:
        self.db.set_setting("model_id", str(self.model_combo.currentData()))
        self.accuracy_preset = str(self.preset_combo.currentData() or "balanced")
        self.db.set_setting("accuracy_preset", self.accuracy_preset)
        self.db.set_setting("device", self.device_combo.currentText())
        self.db.set_setting("cpu_performance_mode", self.cpu_performance_mode)
        self.db.set_setting("cpu_custom_threads", str(self.cpu_custom_threads))
        self._save_online_download_settings()
        self._save_source_settings()
        self._save_output_settings()

    def _save_source_settings(self, *_args) -> None:
        self.source_lrclib_enabled = self.settings_lrclib_check.isChecked() if hasattr(self, "settings_lrclib_check") else self.source_lrclib_enabled
        self.source_local_enabled = self.settings_local_check.isChecked() if hasattr(self, "settings_local_check") else self.source_local_enabled
        self.source_captions_enabled = self.settings_captions_check.isChecked() if hasattr(self, "settings_captions_check") else self.source_captions_enabled
        self.source_synced_enabled = self.settings_synced_check.isChecked() if hasattr(self, "settings_synced_check") else self.source_synced_enabled
        self.source_experimental_enabled = self.settings_experimental_check.isChecked() if hasattr(self, "settings_experimental_check") else self.source_experimental_enabled
        self.db.set_setting("source_lrclib", str(self.source_lrclib_enabled).lower())
        self.db.set_setting("source_local", str(self.source_local_enabled).lower())
        self.db.set_setting("source_captions", str(self.source_captions_enabled).lower())
        self.db.set_setting("source_synced", str(self.source_synced_enabled).lower())
        self.db.set_setting("source_experimental", str(self.source_experimental_enabled).lower())

    def _save_output_settings(self, *_args) -> None:
        sender = self.sender()
        sender_map = {
            "export_lrc_check": "export_lrc_enabled",
            "settings_export_lrc_check": "export_lrc_enabled",
            "export_txt_check": "export_txt_enabled",
            "settings_export_txt_check": "export_txt_enabled",
            "export_srt_check": "export_srt_enabled",
            "settings_export_srt_check": "export_srt_enabled",
            "export_vtt_check": "export_vtt_enabled",
            "settings_export_vtt_check": "export_vtt_enabled",
        }
        updated = False
        for checkbox_attr, value_attr in sender_map.items():
            if sender is getattr(self, checkbox_attr, None):
                setattr(self, value_attr, sender.isChecked())
                updated = True
                break
        if not updated:
            self.export_lrc_enabled = self._checked("export_lrc_check", self.export_lrc_enabled)
            self.export_txt_enabled = self._checked("export_txt_check", self.export_txt_enabled)
            self.export_srt_enabled = self._checked("export_srt_check", self.export_srt_enabled)
            self.export_vtt_enabled = self._checked("export_vtt_check", self.export_vtt_enabled)
        if not any((self.export_lrc_enabled, self.export_txt_enabled, self.export_srt_enabled, self.export_vtt_enabled)):
            self.export_lrc_enabled = True
        self.db.set_setting("export_lrc", str(self.export_lrc_enabled).lower())
        self.db.set_setting("export_txt", str(self.export_txt_enabled).lower())
        self.db.set_setting("export_srt", str(self.export_srt_enabled).lower())
        self.db.set_setting("export_vtt", str(self.export_vtt_enabled).lower())
        self._sync_output_checkboxes()

    def _checked(self, attr: str, fallback: bool) -> bool:
        checkbox = getattr(self, attr, None)
        return checkbox.isChecked() if isinstance(checkbox, QCheckBox) else fallback

    def _sync_output_checkboxes(self) -> None:
        values = {
            "export_lrc_check": self.export_lrc_enabled,
            "export_txt_check": self.export_txt_enabled,
            "export_srt_check": self.export_srt_enabled,
            "export_vtt_check": self.export_vtt_enabled,
            "settings_export_lrc_check": self.export_lrc_enabled,
            "settings_export_txt_check": self.export_txt_enabled,
            "settings_export_srt_check": self.export_srt_enabled,
            "settings_export_vtt_check": self.export_vtt_enabled,
        }
        for attr, checked in values.items():
            checkbox = getattr(self, attr, None)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked() != checked:
                checkbox.blockSignals(True)
                checkbox.setChecked(checked)
                checkbox.blockSignals(False)

    def _enabled_sources(self) -> dict[str, bool]:
        return {
            "lrclib": self.source_lrclib_enabled,
            "local": self.source_local_enabled,
            "captions": self.source_captions_enabled,
            "synced": self.source_synced_enabled,
            "experimental": self.source_experimental_enabled,
        }

    def current_options(self) -> ProcessingOptions:
        return ProcessingOptions(
            model_id=str(self.model_combo.currentData()),
            language=self.language_combo.currentData(),
            device=self.device_combo.currentText(),
            compute_type=self.compute_combo.currentText(),
            cpu_threads=self._selected_cpu_threads(),
            quality_preset=self.preset_combo.currentText(),
            vad_filter=self.vad_check.isChecked(),
            vocal_isolation=self.vocal_check.isChecked(),
            separation_model=str(self.separation_combo.currentData()),
            version_existing=self.version_check.isChecked(),
            embed_lyrics=self.embed_check.isChecked(),
            export_lrc=self.export_lrc_check.isChecked(),
            export_txt=self.export_txt_check.isChecked(),
            export_srt=self.export_srt_check.isChecked(),
            export_vtt=self.export_vtt_check.isChecked(),
            accuracy=AccuracyOptions(
                preset=str(self.preset_combo.currentData() or self.accuracy_preset),
                user_hints=self.accuracy_user_hints,
                use_metadata_hints=self.accuracy_use_metadata,
                two_pass=self.accuracy_two_pass,
                lock_language=self.accuracy_lock_language,
                condition_previous_text=True if self.accuracy_condition_previous else None,
            ),
        )

    def open_accuracy_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Advanced Accuracy")
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        intro = QLabel("Tune lyric detection without changing the main workflow.")
        intro.setObjectName("Muted")
        layout.addWidget(intro)

        use_metadata = QCheckBox("Use file metadata and source names as lyric hints")
        use_metadata.setChecked(self.accuracy_use_metadata)
        two_pass = QCheckBox("Two-pass transcription")
        two_pass.setChecked(self.accuracy_two_pass)
        two_pass.setToolTip("Runs Whisper twice. Slower, but can improve language consistency and repeated hooks.")
        lock_language = QCheckBox("Lock detected language on second pass")
        lock_language.setChecked(self.accuracy_lock_language)
        previous_context = QCheckBox("Use previous lyric context")
        previous_context.setChecked(self.accuracy_condition_previous)
        previous_context.setToolTip("Can help continuity, but may increase repeated hallucinations on some songs.")

        hints_label = QLabel("Lyric hints / names / vocabulary")
        hints_label.setObjectName("Muted")
        hints = QTextEdit()
        hints.setPlaceholderText("Example: artist name, song title, featured artists, unusual words, names, chorus phrases")
        hints.setPlainText(self.accuracy_user_hints)
        hints.setMinimumHeight(110)

        layout.addWidget(use_metadata)
        layout.addWidget(two_pass)
        layout.addWidget(lock_language)
        layout.addWidget(previous_context)
        layout.addWidget(hints_label)
        layout.addWidget(hints)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return
        self.accuracy_use_metadata = use_metadata.isChecked()
        self.accuracy_two_pass = two_pass.isChecked()
        self.accuracy_lock_language = lock_language.isChecked()
        self.accuracy_condition_previous = previous_context.isChecked()
        self.accuracy_user_hints = hints.toPlainText().strip()
        self.db.set_setting("accuracy_use_metadata", str(self.accuracy_use_metadata).lower())
        self.db.set_setting("accuracy_two_pass", str(self.accuracy_two_pass).lower())
        self.db.set_setting("accuracy_lock_language", str(self.accuracy_lock_language).lower())
        self.db.set_setting("accuracy_condition_previous", str(self.accuracy_condition_previous).lower())
        self.db.set_setting("accuracy_user_hints", self.accuracy_user_hints)
        self.statusBar().showMessage("Advanced accuracy settings saved")

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add audio files",
            "",
            "Audio files (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus);;All files (*)",
        )
        self._add_paths([Path(path) for path in paths])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if not folder:
            return
        folder_path = Path(folder)
        self.db.add_recent_folder(folder_path)
        self._add_paths(discover_audio_files(folder_path, recursive=self.recursive_check.isChecked()))

    def add_dropped_sources(self, paths: list[Path]) -> None:
        audio_paths: list[Path] = []
        for path in paths:
            if path.is_dir():
                self.db.add_recent_folder(path)
                audio_paths.extend(discover_audio_files(path, recursive=self.recursive_check.isChecked()))
            else:
                audio_paths.append(path)
        self._add_paths(audio_paths)

    def choose_online_download_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose online download folder",
            str(self.online_download_dir),
        )
        if not folder:
            return
        self.online_download_dir = Path(folder)
        self.online_download_dir.mkdir(parents=True, exist_ok=True)
        self.db.set_setting("online_download_dir", str(self.online_download_dir))
        self._refresh_online_download_dir_labels()
        self.statusBar().showMessage(f"Online downloads will save to {self.online_download_dir}")

    def open_online_download_dir(self) -> None:
        self.online_download_dir.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(self.online_download_dir)

    def _refresh_online_download_dir_labels(self) -> None:
        path_text = str(self.online_download_dir)
        for attr in ("url_folder_label", "online_dir_label"):
            label = getattr(self, attr, None)
            if isinstance(label, QLabel):
                label.setText(path_text)
                label.setToolTip(path_text)

    def _save_online_download_settings(self, *_args) -> None:
        format_combo = getattr(self, "online_format_combo", None)
        preset_combo = getattr(self, "filename_preset_combo", None)
        if isinstance(format_combo, QComboBox):
            self.online_audio_format = format_combo.currentText().lower()
        if isinstance(preset_combo, QComboBox):
            self.online_filename_template = str(preset_combo.currentData() or DEFAULT_FILENAME_TEMPLATE)
        self.db.set_setting("online_audio_format", self.online_audio_format)
        self.db.set_setting("online_filename_template", self.online_filename_template)
        self._refresh_online_download_option_controls()

    def _sync_settings_online_format(self, *_args) -> None:
        combo = getattr(self, "settings_online_format_combo", None)
        if isinstance(combo, QComboBox):
            self.online_audio_format = combo.currentText().lower()
            self.db.set_setting("online_audio_format", self.online_audio_format)
            self._refresh_online_download_option_controls()

    def _sync_settings_filename_preset(self, *_args) -> None:
        combo = getattr(self, "settings_filename_preset_combo", None)
        if isinstance(combo, QComboBox):
            self.online_filename_template = str(combo.currentData() or DEFAULT_FILENAME_TEMPLATE)
            self.db.set_setting("online_filename_template", self.online_filename_template)
            self._refresh_online_download_option_controls()

    def _refresh_online_download_option_controls(self) -> None:
        for attr in ("online_format_combo", "settings_online_format_combo"):
            combo = getattr(self, attr, None)
            if isinstance(combo, QComboBox):
                index = combo.findText(self.online_audio_format.upper())
                if index >= 0 and combo.currentIndex() != index:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(False)
        for attr in ("filename_preset_combo", "settings_filename_preset_combo"):
            combo = getattr(self, attr, None)
            if isinstance(combo, QComboBox):
                index = combo.findData(self.online_filename_template)
                if index < 0:
                    index = combo.findData(DEFAULT_FILENAME_TEMPLATE)
                    self.online_filename_template = DEFAULT_FILENAME_TEMPLATE
                if index >= 0 and combo.currentIndex() != index:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(False)

    def download_url_to_queue(self) -> None:
        self._save_online_download_settings()
        url_text = self.url_input.text().strip()
        urls = parse_video_urls(url_text)
        if not urls:
            if url_text:
                QMessageBox.information(
                    self,
                    "Video URL",
                    "Paste a supported video or audio URL first. YouTube, YouTube Music, Vimeo, and SoundCloud are supported.",
                )
            return
        if self.url_download_worker and self.url_download_worker.isRunning():
            QMessageBox.information(self, "Video URL", "A video download is already running.")
            return
        self.url_download_btn.setEnabled(False)
        self.header_status.setText(f"Downloading {len(urls)} URL audio item(s)")
        self.statusBar().showMessage(f"Downloading {len(urls)} URL audio item(s)")
        self.online_download_dir.mkdir(parents=True, exist_ok=True)
        self.url_download_worker = UrlDownloadWorker(
            urls,
            output_dir=self.online_download_dir,
            audio_format=self.online_audio_format,
            filename_template=self.online_filename_template,
        )
        self.url_download_worker.progress.connect(self._on_url_download_progress)
        self.url_download_worker.failed.connect(self._on_url_download_failed)
        self.url_download_worker.finished_path.connect(self._on_url_download_finished)
        self.url_download_worker.all_finished.connect(self._on_url_download_all_finished)
        self.url_download_worker.start()

    def _on_url_download_progress(self, percent: int, message: str) -> None:
        self.header_status.setText(message)
        self.statusBar().showMessage(message)

    def _on_url_download_failed(self, message: str) -> None:
        self.url_download_btn.setEnabled(True)
        self.header_status.setText("URL download failed")
        self.statusBar().showMessage(message)
        QMessageBox.critical(self, "Video URL download failed", message)

    def _on_url_download_finished(self, path: str) -> None:
        audio_path = Path(path)
        self._add_paths([audio_path])
        self.statusBar().showMessage(f"Added downloaded audio: {audio_path.name}")

    def _on_url_download_all_finished(self, count: int) -> None:
        self.url_download_btn.setEnabled(True)
        self.url_input.clear()
        self.header_status.setText("URL audio ready")
        self.statusBar().showMessage(f"Added {count} downloaded audio item(s)")

    def _add_paths(self, paths: list[Path]) -> None:
        existing = {job.source_path.resolve() for job in self.jobs}
        added = 0
        for path in paths:
            if not is_audio_file(path):
                continue
            resolved = path.resolve()
            if resolved in existing:
                continue
            job = LyricJob(source_path=path)
            self.jobs.append(job)
            existing.add(resolved)
            added += 1
        self._refresh_queue()
        self.statusBar().showMessage(f"Added {added} audio file(s)")

    def clear_queue(self) -> None:
        if self.process_worker and self.process_worker.isRunning():
            QMessageBox.warning(self, "Queue running", "Cancel the running queue before clearing it.")
            return
        self.jobs.clear()
        self.queue_table.setRowCount(0)
        self._refresh_queue_stats()

    def selected_jobs(self) -> list[LyricJob]:
        rows = sorted({index.row() for index in self.queue_table.selectionModel().selectedRows()})
        return [self.jobs[row] for row in rows if 0 <= row < len(self.jobs)]

    def open_selected_job_in_editor(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Editor", "Select a completed queue item first.")
            return
        job = jobs[0]
        if not job.result:
            QMessageBox.information(self, "Editor", "This item has not generated lyrics yet.")
            return
        self.load_job_in_editor(job)

    def find_lyrics_for_selected_job(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Lyrics", "Select a queue item first.")
            return
        self._start_lyrics_source_search(jobs[0])

    def find_lyrics_for_editor_job(self) -> None:
        if not self.current_editor_job:
            QMessageBox.information(self, "Lyrics", "Load a job first.")
            return
        self._start_lyrics_source_search(self.current_editor_job)

    def batch_find_lyrics_sources(self) -> None:
        if self.batch_lyrics_source_worker and self.batch_lyrics_source_worker.isRunning():
            QMessageBox.information(self, "Lyrics", "Batch lyrics search is already running.")
            return
        jobs = self.selected_jobs() or list(self.jobs)
        if not jobs:
            QMessageBox.information(self, "Lyrics", "Add tracks to the queue first.")
            return
        self._save_source_settings()
        self.batch_source_matches = {job.id: [] for job in jobs}
        self.batch_lyrics_dialog = BatchLyricsSourcesDialog(jobs, self)
        self.batch_lyrics_dialog.apply_sources_btn.clicked.connect(self.apply_batch_source_matches)
        self.batch_lyrics_dialog.save_txt_btn.clicked.connect(self.save_batch_source_text)
        self.batch_lyrics_dialog.show()
        self.batch_lyrics_dialog.set_busy(True, "Searching lyric sources")
        self.batch_lyrics_source_worker = BatchLyricsSourceWorker(jobs, self._enabled_sources())
        self.batch_lyrics_source_worker.progress.connect(self._on_batch_lyrics_progress)
        self.batch_lyrics_source_worker.item_found.connect(self._on_batch_lyrics_item_found)
        self.batch_lyrics_source_worker.failed.connect(self._on_batch_lyrics_failed)
        self.batch_lyrics_source_worker.all_finished.connect(self._on_batch_lyrics_finished)
        self.batch_lyrics_source_worker.start()

    def _on_batch_lyrics_progress(self, percent: int, message: str) -> None:
        if self.batch_lyrics_dialog:
            self.batch_lyrics_dialog.set_progress(percent, message)
        self.header_status.setText(message)
        self.statusBar().showMessage(message)

    def _on_batch_lyrics_item_found(self, job_id: str, candidates: list[LyricCandidate]) -> None:
        self.batch_source_matches[job_id] = candidates
        job = self._job_by_id(job_id)
        if job:
            best = _best_batch_candidate(candidates)
            if best:
                job.message = f"Source match: {best.provider} {best.confidence}%"
            else:
                job.message = "No source match"
            self._update_job_row(job)
        if self.batch_lyrics_dialog:
            self.batch_lyrics_dialog.set_candidates(job_id, candidates)

    def _on_batch_lyrics_failed(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _on_batch_lyrics_finished(self) -> None:
        if self.batch_lyrics_dialog:
            self.batch_lyrics_dialog.set_busy(False, "Batch source search ready")
        self.header_status.setText("Batch lyrics ready")
        self.statusBar().showMessage("Batch source search complete")

    def apply_batch_source_matches(self) -> None:
        if self.process_worker and self.process_worker.isRunning():
            QMessageBox.information(self, "Lyrics", "Wait for the current queue to finish before applying batch source lyrics.")
            return
        plain_mode = self.batch_lyrics_dialog.plain_mode() if self.batch_lyrics_dialog else "Save TXT only"
        service = LyricsSourceService(self._enabled_sources())
        applied = 0
        saved_plain = 0
        queued_ai: list[LyricJob] = []
        skipped = 0
        for job_id, candidates in self.batch_source_matches.items():
            job = self._job_by_id(job_id)
            candidate = _best_batch_candidate(candidates)
            if not job or not candidate:
                skipped += 1
                continue
            if not _candidate_is_safe_for_batch(candidate, has_ai_timing=bool(job.result)):
                job.message = "Source match needs review"
                skipped += 1
                self._update_job_row(job)
                continue
            try:
                lyrics = service.fetch(candidate)
            except Exception as exc:
                job.message = f"Source fetch failed: {exc}"
                skipped += 1
                self._update_job_row(job)
                continue
            if lyrics.synced:
                self._apply_provider_lyrics(job, lyrics, open_editor=False, save_outputs=True)
                applied += 1
            elif job.result:
                if plain_mode == "Use AI sync":
                    self._apply_provider_lyrics(job, lyrics, threshold_override=0.68, open_editor=False, save_outputs=True)
                    applied += 1
                elif plain_mode == "Save TXT only":
                    saved_plain += self._save_provider_text(job, lyrics)
                else:
                    job.message = "Plain source skipped"
                    skipped += 1
                    self._update_job_row(job)
            else:
                if plain_mode == "Use AI sync":
                    self.pending_provider_applies[job.id] = (lyrics, 0.68)
                    job.status = JobStatus.PENDING
                    job.progress = 0
                    job.message = "Queued AI timing for source lyrics"
                    queued_ai.append(job)
                    self._update_job_row(job)
                elif plain_mode == "Save TXT only":
                    saved_plain += self._save_provider_text(job, lyrics)
                else:
                    job.message = "Plain source skipped"
                    skipped += 1
                    self._update_job_row(job)
        if queued_ai:
            self._start_jobs(queued_ai)
        self._refresh_queue()
        summary = f"Applied/saved {applied} synced source match(es); saved {saved_plain} plain TXT file(s); queued {len(queued_ai)} AI sync job(s); skipped {skipped}."
        self.statusBar().showMessage(summary)
        QMessageBox.information(self, "Batch Sources", summary)

    def save_batch_source_text(self) -> None:
        service = LyricsSourceService(self._enabled_sources())
        saved = 0
        for job_id, candidates in self.batch_source_matches.items():
            job = self._job_by_id(job_id)
            candidate = _best_batch_candidate(candidates)
            if not job or not candidate:
                continue
            try:
                lyrics = service.fetch(candidate)
            except Exception:
                continue
            saved += self._save_provider_text(job, lyrics)
        self.statusBar().showMessage(f"Saved {saved} provider TXT file(s)")

    def _save_provider_text(self, job: LyricJob, lyrics: ProviderLyrics) -> int:
        text = render_txt(lyrics.lines) if lyrics.synced else "\n".join(parse_plain_text(lyrics.plain_text)) + "\n"
        if not text.strip():
            return 0
        provider = _safe_provider_suffix(lyrics.provider)
        target = next_versioned_path(job.source_path.with_suffix(f".{provider}.txt"))
        target.write_text(text, encoding="utf-8")
        job.message = f"Saved source TXT: {target.name}"
        self._update_job_row(job)
        return 1

    def _start_lyrics_source_search(self, job: LyricJob) -> None:
        if self.lyrics_source_worker and self.lyrics_source_worker.isRunning():
            QMessageBox.information(self, "Lyrics", "Lyrics search is already running.")
            return
        self._save_source_settings()
        self.lyrics_source_job = job
        self.lyrics_source_dialog = LyricsSourcesDialog(self._enabled_sources(), self)
        try:
            query = LyricsSourceService(self._enabled_sources()).build_query(job.source_path)
            self.lyrics_source_dialog.set_search_values(query.title, query.artist, query.album)
        except Exception:
            pass
        self.lyrics_source_dialog.apply_btn.clicked.connect(self.apply_selected_lyrics_candidate)
        self.lyrics_source_dialog.preview_btn.clicked.connect(self.preview_selected_lyrics_candidate)
        self.lyrics_source_dialog.save_txt_btn.clicked.connect(self.save_selected_lyrics_text)
        self.lyrics_source_dialog.search_btn.clicked.connect(lambda: self._rerun_lyrics_source_search(job))
        self.lyrics_source_dialog.show()
        self._rerun_lyrics_source_search(job)

    def _rerun_lyrics_source_search(self, job: LyricJob) -> None:
        if not self.lyrics_source_dialog:
            return
        if self.lyrics_source_worker and self.lyrics_source_worker.isRunning():
            return
        enabled = self.lyrics_source_dialog.enabled_sources()
        self.source_lrclib_enabled = enabled["lrclib"]
        self.source_local_enabled = enabled["local"]
        self.source_captions_enabled = enabled["captions"]
        self.source_synced_enabled = enabled["synced"]
        self.source_experimental_enabled = enabled["experimental"]
        if hasattr(self, "settings_lrclib_check"):
            self.settings_lrclib_check.setChecked(self.source_lrclib_enabled)
            self.settings_local_check.setChecked(self.source_local_enabled)
            self.settings_captions_check.setChecked(self.source_captions_enabled)
            self.settings_synced_check.setChecked(self.source_synced_enabled)
            self.settings_experimental_check.setChecked(self.source_experimental_enabled)
        self._save_source_settings()
        self.lyrics_source_dialog.set_busy(True, "Searching sources")
        self.lyrics_source_worker = LyricsSourceWorker(
            job.source_path,
            enabled,
            self.lyrics_source_dialog.search_values(),
        )
        self.lyrics_source_worker.progress.connect(self._on_lyrics_source_progress)
        self.lyrics_source_worker.found.connect(self._on_lyrics_source_found)
        self.lyrics_source_worker.failed.connect(self._on_lyrics_source_failed)
        self.lyrics_source_worker.start()

    def _on_lyrics_source_progress(self, percent: int, message: str) -> None:
        if self.lyrics_source_dialog:
            self.lyrics_source_dialog.set_progress(percent, message)
        self.header_status.setText(message)
        self.statusBar().showMessage(message)

    def _on_lyrics_source_found(self, candidates: list[LyricCandidate]) -> None:
        if self.lyrics_source_dialog:
            self.lyrics_source_dialog.set_candidates(candidates)
            self.lyrics_source_dialog.set_busy(False, f"{len(candidates)} found")
        self.header_status.setText("Lyrics search ready")
        self.statusBar().showMessage(f"Found {len(candidates)} lyric source candidate(s)")

    def _on_lyrics_source_failed(self, message: str) -> None:
        if self.lyrics_source_dialog:
            self.lyrics_source_dialog.set_busy(False, "Search failed")
        self.header_status.setText("Lyrics search failed")
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Lyrics", message)

    def preview_selected_lyrics_candidate(self) -> None:
        lyrics = self._selected_or_pasted_lyrics()
        if not lyrics:
            return
        text = render_lrc(lyrics.lines) if lyrics.synced else lyrics.plain_text
        if self.lyrics_source_dialog:
            self.lyrics_source_dialog.set_preview(text)

    def apply_selected_lyrics_candidate(self) -> None:
        job = self.lyrics_source_job
        if not job:
            return
        lyrics = self._selected_or_pasted_lyrics()
        if not lyrics:
            return
        if not lyrics.synced and not job.result:
            if self.process_worker and self.process_worker.isRunning():
                QMessageBox.information(self, "Lyrics", "AI timing is already running. Apply these lyrics after the current queue finishes.")
                return
            threshold = self.lyrics_source_dialog.sync_threshold() if self.lyrics_source_dialog else 0.68
            self.pending_provider_apply = (job.id, lyrics, threshold)
            if self.lyrics_source_dialog:
                self.lyrics_source_dialog.accept()
            job.status = JobStatus.PENDING
            job.progress = 0
            job.message = "Generating AI timing for lyric source"
            self._refresh_queue()
            self.statusBar().showMessage("Running AI timing first, then Lyricrafter will match the selected lyrics.")
            self._start_jobs([job])
            return
        self._apply_provider_lyrics(job, lyrics)
        if self.lyrics_source_dialog:
            self.lyrics_source_dialog.accept()

    def save_selected_lyrics_text(self) -> None:
        job = self.lyrics_source_job
        lyrics = self._selected_or_pasted_lyrics()
        if not job or not lyrics:
            return
        text = render_txt(lyrics.lines) if lyrics.synced else "\n".join(parse_plain_text(lyrics.plain_text)) + "\n"
        if not text.strip():
            QMessageBox.information(self, "Lyrics", "No plain lyric text is available to save.")
            return
        provider = "".join(char for char in lyrics.provider.replace("/", "-") if char.isalnum() or char in {" ", "-", "_"}).strip()
        suffix = f".{provider or 'lyrics'}.txt"
        target = next_versioned_path(job.source_path.with_suffix(suffix))
        target.write_text(text, encoding="utf-8")
        self.statusBar().showMessage(f"Saved {target.name}")

    def _selected_or_pasted_lyrics(self) -> ProviderLyrics | None:
        pasted = self.lyrics_source_dialog.pasted_lyrics() if self.lyrics_source_dialog else ""
        if pasted:
            return ProviderLyrics(
                provider="Paste",
                title=self.lyrics_source_job.source_path.stem if self.lyrics_source_job else "Pasted lyrics",
                synced=False,
                plain_text=pasted,
                confidence=100,
            )
        candidate = self._selected_lyrics_candidate()
        if not candidate:
            return None
        try:
            return LyricsSourceService(self._enabled_sources()).fetch(candidate)
        except Exception as exc:
            QMessageBox.warning(self, "Lyrics", f"Could not load lyrics: {exc}")
            return None

    def _selected_lyrics_candidate(self) -> LyricCandidate | None:
        dialog = self.lyrics_source_dialog
        if not dialog:
            return None
        candidate = dialog.selected_candidate()
        if candidate is None:
            QMessageBox.information(self, "Lyrics", "Select a lyric source first.")
        return candidate

    def _apply_provider_lyrics(
        self,
        job: LyricJob,
        lyrics: ProviderLyrics,
        threshold_override: float | None = None,
        open_editor: bool = True,
        save_outputs: bool = True,
    ) -> None:
        warnings: list[str] = [f"Applied {lyrics.provider} lyrics. Review before saving."]
        section_hints: list[dict[str, object]] = []
        if lyrics.synced and lyrics.lines:
            lines = cleanup_lyric_lines(lyrics.lines)
        else:
            provider_lines, provider_sections = parse_plain_text_with_sections(lyrics.plain_text)
            base_lines = job.result.lines if job.result else []
            threshold = (
                threshold_override
                if threshold_override is not None
                else self.lyrics_source_dialog.sync_threshold() if self.lyrics_source_dialog else 0.56
            )
            if lyrics.provider.casefold().startswith("synced/genius") and threshold < 0.62:
                threshold = 0.62
            lines, align_warnings = align_plain_lyrics(base_lines, provider_lines, threshold=threshold)
            warnings.extend(align_warnings)
            if provider_sections and len(lines) == len(provider_lines):
                section_hints = [
                    {
                        "start_row": hint.start_line,
                        "end_row": hint.end_line,
                        "kind": hint.kind,
                        "source": lyrics.provider,
                    }
                    for hint in provider_sections
                ]
            if lyrics.provider.casefold().startswith("synced/genius"):
                warnings.append("Genius plain lyrics were synced to AI timing. Review weak matches before saving.")

        if job.result is None:
            outputs = output_pair_for_audio(job.source_path, version_existing=self.version_check.isChecked())
            job.result = JobResult(
                lrc_path=outputs.lrc,
                txt_path=outputs.txt,
                lines=lines,
                plain_text=render_txt(lines),
                srt_path=outputs.srt if self.export_srt_enabled else None,
                vtt_path=outputs.vtt if self.export_vtt_enabled else None,
                review_warnings=warnings,
                section_hints=section_hints,
            )
            job.status = JobStatus.COMPLETE
            job.progress = 100
        else:
            job.result.lines[:] = lines
            job.result.plain_text = render_txt(lines)
            job.result.review_warnings.extend(warnings)
            job.result.section_hints = section_hints
        job.message = f"Lyrics from {lyrics.provider}"
        if save_outputs and job.result:
            self._write_result_outputs(job.result)
        self._refresh_queue()
        if open_editor:
            self.load_job_in_editor(job)
        if open_editor and job.result:
            self._show_quality_issues(check_lyrics_quality(job.result.lines), job.result.review_warnings)
        self.statusBar().showMessage("Lyrics applied and saved." if save_outputs else "Lyrics applied. Review and save outputs.")

    def remove_selected_jobs(self) -> None:
        if self.process_worker and self.process_worker.isRunning():
            QMessageBox.warning(self, "Queue running", "Cancel the running queue before removing items.")
            return
        selected_ids = {job.id for job in self.selected_jobs()}
        if not selected_ids:
            return
        self.jobs = [job for job in self.jobs if job.id not in selected_ids]
        self._refresh_queue()

    def regenerate_selected_jobs(self) -> None:
        if self.process_worker and self.process_worker.isRunning():
            QMessageBox.warning(self, "Queue running", "Cancel the running queue before regenerating items.")
            return
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Regenerate", "Select one or more queue items to regenerate.")
            return
        for job in jobs:
            job.status = JobStatus.PENDING
            job.progress = 0
            job.message = "Queued for regeneration"
            job.result = None
            job.error = None
        self._refresh_queue()
        self._start_jobs(jobs)

    def enrich_selected_metadata(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Metadata", "Select one or more queue items first.")
            return
        if self.metadata_worker and self.metadata_worker.isRunning():
            QMessageBox.information(self, "Metadata", "Metadata enrichment is already running.")
            return
        paths = [job.source_path for job in jobs]
        for job in jobs:
            job.message = "Queued for metadata enrichment"
            self._update_job_row(job)
        self.header_status.setText("Metadata enrichment running")
        self.statusBar().showMessage("Metadata enrichment running")
        self.metadata_worker = MetadataWorker(paths)
        self.metadata_worker.progress.connect(self._on_metadata_progress)
        self.metadata_worker.file_finished.connect(self._on_metadata_file_finished)
        self.metadata_worker.failed.connect(self._on_metadata_failed)
        self.metadata_worker.all_finished.connect(self._on_metadata_all_finished)
        self.metadata_worker.start()

    def _on_metadata_progress(self, percent: int, message: str) -> None:
        self.header_status.setText(f"{message} ({percent}%)")
        self.statusBar().showMessage(message)

    def _on_metadata_file_finished(self, path: str, message: str) -> None:
        resolved = Path(path)
        for job in self.jobs:
            if job.source_path == resolved:
                job.message = message
                self._update_job_row(job)
                break
        self.statusBar().showMessage(message)

    def _on_metadata_failed(self, message: str) -> None:
        self.header_status.setText("Metadata warning")
        self.statusBar().showMessage(message)

    def _on_metadata_all_finished(self, count: int) -> None:
        self.header_status.setText("Metadata complete")
        self.statusBar().showMessage(f"Metadata embedded for {count} file(s)")

    def embed_selected_job_lyrics(self) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Embed", "Select a completed queue item first.")
            return
        completed = 0
        failures: list[str] = []
        for job in jobs:
            ok, message = self._embed_job_lyrics(job)
            if ok:
                completed += 1
            else:
                failures.append(f"{job.source_path.name}: {message}")
            self._update_job_row(job)
        if failures:
            QMessageBox.warning(self, "Embed", "\n".join(failures[:8]))
        self.statusBar().showMessage(f"Embedded lyrics for {completed} file(s)")

    def embed_current_editor_lyrics(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            QMessageBox.information(self, "Embed", "Load a completed lyric job first.")
            return
        self._sync_current_editor_result()
        ok, message = self._embed_job_lyrics(self.current_editor_job)
        self._update_job_row(self.current_editor_job)
        if ok:
            QMessageBox.information(self, "Embed", message)
        else:
            QMessageBox.warning(self, "Embed", message)
        self.statusBar().showMessage(message)

    def _embed_job_lyrics(self, job: LyricJob) -> tuple[bool, str]:
        if not job.result:
            return False, "No lyrics to embed yet."
        if self.current_editor_job and self.current_editor_job.id == job.id:
            self._sync_current_editor_result()
        if not can_embed_lyrics(job.source_path):
            return False, f"Embedding is not supported for {job.source_path.suffix or 'this file type'}."
        lines = job.result.lines
        if not lines:
            return False, "No lyric lines to embed."
        try:
            self._release_player_for_path(job.source_path)
            embedded = embed_lyrics(job.source_path, lines)
        except PermissionError:
            message = f"Permission denied. Close any player or tag editor using {job.source_path.name}, then retry."
            job.result.embedded = False
            job.result.embed_error = message
            return False, message
        except OSError as exc:
            message = f"Could not embed lyrics: {exc}"
            job.result.embedded = False
            job.result.embed_error = message
            return False, message
        if not embedded:
            return False, "No lyric text was embedded."
        job.result.embedded = True
        job.result.embed_error = None
        return True, f"Embedded lyrics in {job.source_path.name}"

    def _release_player_for_path(self, path: Path) -> None:
        if not self.current_editor_job or self.current_editor_job.source_path != path:
            return
        self.player.stop()
        self.player.setSource(QUrl())

    def show_queue_context_menu(self, position) -> None:
        row = self.queue_table.rowAt(position.y())
        if row >= 0 and not self.queue_table.selectionModel().isRowSelected(row):
            self.queue_table.selectRow(row)
        menu = QMenu(self)
        open_action = menu.addAction("Open in Editor")
        lyrics_action = menu.addAction("Find Lyrics")
        batch_lyrics_action = menu.addAction("Batch Sources")
        embed_action = menu.addAction("Embed Lyrics")
        metadata_action = menu.addAction("Enrich Metadata")
        regenerate_action = menu.addAction("Regenerate Lyrics")
        remove_action = menu.addAction("Remove")
        menu.addSeparator()
        clear_action = menu.addAction("Clear Queue")
        action = menu.exec(self.queue_table.viewport().mapToGlobal(position))
        if action == open_action:
            self.open_selected_job_in_editor()
        elif action == lyrics_action:
            self.find_lyrics_for_selected_job()
        elif action == batch_lyrics_action:
            self.batch_find_lyrics_sources()
        elif action == embed_action:
            self.embed_selected_job_lyrics()
        elif action == metadata_action:
            self.enrich_selected_metadata()
        elif action == regenerate_action:
            self.regenerate_selected_jobs()
        elif action == remove_action:
            self.remove_selected_jobs()
        elif action == clear_action:
            self.clear_queue()

    def start_queue(self) -> None:
        pending = [job for job in self.jobs if job.status in {JobStatus.PENDING, JobStatus.FAILED}]
        if not pending:
            QMessageBox.information(self, "Queue", "There are no pending jobs to process.")
            return
        self._start_jobs(pending)

    def _start_jobs(self, jobs: list[LyricJob]) -> None:
        self._save_settings()
        self.process_worker = ProcessWorker(jobs, self.current_options(), self.engine)
        self.process_worker.job_changed.connect(self._on_job_changed)
        self.process_worker.progress_changed.connect(self._on_job_progress)
        self.process_worker.job_finished.connect(self._on_job_finished)
        self.process_worker.job_failed.connect(lambda _job_id, message: self.statusBar().showMessage(message))
        self.process_worker.all_finished.connect(self._on_queue_finished)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.process_worker.start()

    def cancel_queue(self) -> None:
        if self.process_worker:
            self.process_worker.cancel()
            self.statusBar().showMessage("Queue will cancel after the current file")

    def retry_failed(self) -> None:
        for job in self.jobs:
            if job.status == JobStatus.FAILED:
                job.status = JobStatus.PENDING
                job.progress = 0
                job.message = "Queued"
                job.error = None
        self._refresh_queue()

    def _on_job_progress(self, job_id: str, progress: int, message: str) -> None:
        job = self._job_by_id(job_id)
        if not job:
            return
        job.progress = progress
        job.message = message
        self._update_job_row(job)
        self.statusBar().showMessage(message)

    def _on_job_changed(self, job: LyricJob) -> None:
        self.db.save_job(job)
        self._update_job_row(job)

    def _on_job_finished(self, job_id: str, result: JobResult) -> None:
        job = self._job_by_id(job_id)
        if job:
            job.result = result
            if job_id in self.pending_provider_applies:
                lyrics, threshold = self.pending_provider_applies.pop(job_id)
                self._apply_provider_lyrics(job, lyrics, threshold_override=threshold, open_editor=False)
                return
            if self.pending_provider_apply and self.pending_provider_apply[0] == job_id:
                _pending_job_id, lyrics, threshold = self.pending_provider_apply
                self.pending_provider_apply = None
                self._apply_provider_lyrics(job, lyrics, threshold_override=threshold)
                return
            self.load_job_in_editor(job)
        self._refresh_history()

    def _on_queue_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage("Queue finished")
        self._refresh_history()

    def _refresh_queue(self) -> None:
        self._refresh_queue_stats()
        self.queue_table.setRowCount(len(self.jobs))
        for job in self.jobs:
            self._update_job_row(job)

    def _update_job_row(self, job: LyricJob) -> None:
        try:
            row = self.jobs.index(job)
        except ValueError:
            return
        outputs = ""
        if job.result:
            outputs = ", ".join(self._result_output_names(job.result))
            if job.result.embedded:
                outputs += " + embedded"
            elif job.result.embed_error:
                outputs += " + embed skipped"
        values = [
            job.source_path.name,
            job.status.value,
            job.message,
            outputs,
        ]
        for column, value in zip([0, 1, 3, 4], values):
            item = QTableWidgetItem(value)
            item.setData(Qt.UserRole, job.id)
            item.setToolTip(value)
            self.queue_table.setItem(row, column, item)
        self.queue_table.setRowHeight(row, 42)
        progress_bar = self.queue_table.cellWidget(row, 2)
        if not isinstance(progress_bar, QProgressBar):
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setFormat("%p%")
            self.queue_table.setCellWidget(row, 2, progress_bar)
        progress_bar.setValue(job.progress)
        self._refresh_queue_stats()

    def _refresh_queue_stats(self) -> None:
        if not hasattr(self, "stat_queued_value"):
            return
        complete = sum(1 for job in self.jobs if job.status == JobStatus.COMPLETE)
        failed = sum(1 for job in self.jobs if job.status == JobStatus.FAILED)
        self.stat_queued_value.setText(str(len(self.jobs)))
        self.stat_done_value.setText(str(complete))
        self.stat_failed_value.setText(str(failed))
        self._refresh_batch_progress()

    def _refresh_batch_progress(self) -> None:
        if not hasattr(self, "stat_progress_value"):
            return
        if not self.jobs:
            self.stat_progress_value.setText("0%")
            return
        total = sum(max(0, min(100, job.progress)) for job in self.jobs)
        self.stat_progress_value.setText(f"{int(total / len(self.jobs))}%")

    def _result_output_names(self, result: JobResult) -> list[str]:
        names: list[str] = []
        for path in (result.lrc_path, result.txt_path, result.srt_path, result.vtt_path):
            if path and path.exists():
                names.append(path.name)
        if not names:
            names.extend([result.lrc_path.name, result.txt_path.name])
        return names

    def _job_by_id(self, job_id: str) -> LyricJob | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    def load_selected_job_in_editor(self) -> None:
        selected = self.queue_table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        if row < len(self.jobs):
            self.load_job_in_editor(self.jobs[row])

    def load_job_in_editor(self, job: LyricJob) -> None:
        if not job.result:
            return
        self.current_editor_job = job
        self._section_overrides = [
            SectionOverride(
                start_row=int(hint.get("start_row", 0)),
                end_row=int(hint.get("end_row", 0)),
                kind=str(hint.get("kind", "Verse")),
                source=str(hint.get("source", "source")),
            )
            for hint in job.result.section_hints
            if str(hint.get("kind", "")) in SECTION_KINDS
        ]
        self._section_master = None
        if self.section_loop_btn.isChecked():
            self.section_loop_btn.setChecked(False)
        self._pending_missing_lines.clear()
        self._refresh_missing_line_controls()
        self.editor_title.setText(str(job.source_path))
        self.now_playing_label.setText("Ready for sync review")
        self._current_sync_row = -1
        self._set_editor_lines(job.result.lines, reset_history=True, record_history=False)
        self._show_quality_issues(check_lyrics_quality(job.result.lines), job.result.review_warnings)
        if job.result.lines:
            self.preview_original_label.setText(job.result.lines[0].text)
            self.preview_translation_label.setText(job.result.lines[0].translation or "Translation will appear here")
        else:
            self.preview_original_label.setText("No lyric loaded")
            self.preview_translation_label.setText("")
        self.player.setSource(QUrl.fromLocalFile(str(job.source_path.resolve())))
        self._load_editor_waveform(job.source_path)
        self._set_workspace_page(1)

    def play_current_audio(self) -> None:
        if not self.current_editor_job:
            QMessageBox.information(self, "Editor", "Load a completed job first.")
            return
        self.player.play()

    def _load_editor_waveform(self, path: Path) -> None:
        self.waveform.clear_waveform()
        self.waveform.set_lines(self._lines_from_editor())
        worker = WaveformWorker(path)
        worker.loaded.connect(self._on_waveform_loaded)
        worker.failed.connect(self._on_waveform_failed)
        worker.finished.connect(lambda current=worker: self._release_waveform_worker(current))
        self.waveform_workers.append(worker)
        worker.start()

    def _on_waveform_loaded(self, path: str, peaks: list[float], duration: float) -> None:
        if not self.current_editor_job or self.current_editor_job.source_path.resolve() != Path(path).resolve():
            return
        self.waveform.set_waveform(peaks, duration)
        self.waveform.set_lines(self._lines_from_editor())
        self.statusBar().showMessage("Waveform ready")

    def _on_waveform_failed(self, path: str, message: str) -> None:
        if self.current_editor_job and self.current_editor_job.source_path.resolve() == Path(path).resolve():
            self.statusBar().showMessage(f"Waveform unavailable: {message}")

    def _release_waveform_worker(self, worker: WaveformWorker) -> None:
        if worker in self.waveform_workers:
            self.waveform_workers.remove(worker)
        worker.deleteLater()

    def _sync_player_position(self, position_ms: int) -> None:
        if self._section_loop_bounds and not self._loop_seek_active:
            loop_start, loop_end = self._section_loop_bounds
            if position_ms >= int(loop_end * 1000):
                self._loop_seek_active = True
                self.player.setPosition(int(loop_start * 1000))
                QTimer.singleShot(80, self._release_loop_seek)
                return
        duration = self.player.duration()
        if duration > 0:
            self.timeline_slider.blockSignals(True)
            if not self._seeking_slider:
                self.timeline_slider.setValue(int((position_ms / duration) * 1000))
            self.timeline_slider.blockSignals(False)
        self.current_time_label.setText(_format_position(position_ms))
        self.waveform.set_playhead(position_ms / 1000)
        self._highlight_current_lyric(position_ms / 1000)

    def _sync_player_duration(self, duration_ms: int) -> None:
        self.duration_label.setText(_format_position(duration_ms))
        self._refresh_song_structure()
        self._sync_player_position(self.player.position())

    def _begin_slider_seek(self) -> None:
        self._seeking_slider = True

    def _preview_slider_seek(self, value: int) -> None:
        duration = self.player.duration()
        if duration <= 0:
            return
        position = int((value / 1000) * duration)
        self.current_time_label.setText(_format_position(position))
        self._highlight_current_lyric(position / 1000)

    def _commit_slider_seek(self) -> None:
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(int((self.timeline_slider.value() / 1000) * duration))
        self._seeking_slider = False

    def seek_relative(self, delta_ms: int) -> None:
        duration = self.player.duration()
        current = self.player.position()
        target = max(0, current + delta_ms)
        if duration > 0:
            target = min(duration, target)
        self.player.setPosition(target)

    def _highlight_current_lyric(self, seconds: float) -> None:
        row = self._row_for_position(seconds)
        if row < 0 or row == self._current_sync_row:
            return
        self._current_sync_row = row
        self.waveform.set_active_row(row)
        self._set_active_section_for_row(row)
        self._syncing_table_selection = True
        try:
            self.lyric_table.selectRow(row)
        finally:
            self._syncing_table_selection = False
        item = self.lyric_table.item(row, 1)
        if item:
            self.lyric_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            original = item.text()
            translation_item = self.lyric_table.item(row, 2)
            translation = translation_item.text() if translation_item else ""
            self.now_playing_label.setText(original)
            self.preview_original_label.setText(original)
            self.preview_translation_label.setText(translation or "Translation will appear here")
            self._refresh_preview_mode()

    def _seek_to_clicked_lyric(self, row: int, _column: int) -> None:
        self._seek_to_lyric_row(row)

    def _seek_to_selected_lyric(self) -> None:
        if self._syncing_table_selection:
            return
        rows = self.lyric_table.selectionModel().selectedRows()
        self.waveform.set_selected_rows({index.row() for index in rows})
        if not rows:
            return
        self._seek_to_lyric_row(rows[0].row())
        if self.section_loop_btn.isChecked():
            section = self._section_for_selected_row()
            if section:
                self._section_loop_bounds = (section.start, section.end)
                self.section_loop_btn.setText(f"Looping {section.label}")
        self._update_section_repair_quality()

    def _seek_to_lyric_row(self, row: int) -> None:
        start_item = self.lyric_table.item(row, 0)
        text_item = self.lyric_table.item(row, 1)
        if not start_item or not text_item:
            return
        try:
            start = max(0.0, float(start_item.text()))
        except ValueError:
            return
        self.player.setPosition(int(start * 1000))
        self._current_sync_row = row
        self._set_active_section_for_row(row)
        self.now_playing_label.setText(text_item.text())
        self.preview_original_label.setText(text_item.text())
        translation_item = self.lyric_table.item(row, 2)
        translation = translation_item.text() if translation_item else ""
        self.preview_translation_label.setText(translation or "Translation will appear here")
        self._refresh_preview_mode()

    def _select_waveform_line(self, row: int) -> None:
        if 0 <= row < self.lyric_table.rowCount():
            self.lyric_table.selectRow(row)
            self._seek_to_lyric_row(row)

    def _begin_waveform_timing_drag(self) -> None:
        self._waveform_drag_snapshot = list(self._lines_from_editor())

    def _apply_waveform_timing(self, row: int, start: float) -> None:
        if not 0 <= row < self.lyric_table.rowCount():
            return
        previous = self._waveform_drag_snapshot or list(self._lines_from_editor())
        self._waveform_drag_snapshot = None
        lines = self._lines_from_editor()
        line = lines[row]
        lines[row] = LyricLine(start=max(0.0, start), text=line.text, translation=line.translation)
        self._set_editor_lines(lines, record_history=False)
        self._record_editor_change(previous)
        self.lyric_table.selectRow(row)
        self.player.setPosition(int(max(0.0, start) * 1000))
        self.statusBar().showMessage(f"Retimed line {row + 1} to {_format_position(int(start * 1000))}")

    def _refresh_song_structure(self, lines: list[LyricLine] | None = None) -> None:
        if not hasattr(self, "song_map"):
            return
        current_lines = list(lines) if lines is not None else self._lines_from_editor()
        duration = max(self.player.duration() / 1000, current_lines[-1].start + 4.0 if current_lines else 0.0)
        self._song_sections = detect_lyric_sections(
            current_lines,
            duration=duration,
            overrides=self._section_overrides,
        )
        self.song_map.set_sections(self._song_sections, duration)
        self.section_list.clear()
        for index, section in enumerate(self._song_sections):
            confidence = round(section.confidence * 100)
            source_note = ""
            if section.source == "manual":
                source_note = " | Manual"
            elif section.source != "auto":
                source_note = f" | {section.source.rsplit('/', 1)[-1]}"
            item = QListWidgetItem(
                f"{_format_position(int(section.start * 1000))}  {section.label}"
                f" | {section.line_count} lines | {confidence}%{source_note}"
            )
            item.setData(Qt.UserRole, index)
            item.setToolTip(
                f"Lines {section.start_row + 1}-{section.end_row + 1}. "
                "Click to select this section and jump playback."
            )
            self.section_list.addItem(item)
        repeated = len([section for section in self._song_sections if section.repeat_group])
        self.section_summary_label.setText(
            f"{len(self._song_sections)} sections | {repeated} repeated section(s)"
            if self._song_sections
            else "No lyric sections detected."
        )
        self.section_detect_label.setText(
            f"{len(self._song_sections)} sections detected" if self._song_sections else "No structure detected"
        )
        if self._section_master:
            self.section_master_label.setText(f"Master: {self._section_master.label}")
        else:
            self.section_master_label.setText("Master: none")
        self._decorate_section_rows()
        self._update_section_repair_quality()

    def _decorate_section_rows(self) -> None:
        colors = {
            "Intro": "#182635",
            "Verse": "#152330",
            "Pre-Chorus": "#251f35",
            "Chorus": "#15302e",
            "Post-Chorus": "#2b2030",
            "Hook": "#302519",
            "Bridge": "#30291c",
            "Outro": "#23272d",
        }
        blocked = self.lyric_table.blockSignals(True)
        try:
            for row in range(self.lyric_table.rowCount()):
                for column in range(self.lyric_table.columnCount()):
                    item = self.lyric_table.item(row, column)
                    if item:
                        item.setBackground(QBrush())
                        item.setToolTip("")
            for section in self._song_sections:
                brush = QBrush(QColor(colors.get(section.kind, "#19232d")))
                tooltip = (
                    f"{section.label} | Lines {section.start_row + 1}-{section.end_row + 1} | "
                    f"{round(section.confidence * 100)}% confidence"
                )
                for row in range(section.start_row, section.end_row + 1):
                    for column in range(self.lyric_table.columnCount()):
                        item = self.lyric_table.item(row, column)
                        if item:
                            item.setBackground(brush)
                            item.setToolTip(tooltip)
        finally:
            self.lyric_table.blockSignals(blocked)

    def redetect_song_structure(self) -> None:
        self._refresh_song_structure()
        self.statusBar().showMessage(f"Detected {len(self._song_sections)} lyric sections")

    def _section_for_selected_row(self) -> LyricSection | None:
        rows = self.lyric_table.selectionModel().selectedRows()
        row = rows[0].row() if rows else self.lyric_table.currentRow()
        return next(
            (section for section in self._song_sections if section.start_row <= row <= section.end_row),
            None,
        )

    def _select_song_section(self, index: int) -> None:
        if not 0 <= index < len(self._song_sections):
            return
        section = self._song_sections[index]
        self.lyric_table.setCurrentCell(section.start_row, 1)
        self.lyric_table.clearSelection()
        selection = QTableWidgetSelectionRange(
            section.start_row,
            0,
            section.end_row,
            self.lyric_table.columnCount() - 1,
        )
        self.lyric_table.setRangeSelected(selection, True)
        if self.section_list.count() > index:
            self.section_list.setCurrentRow(index)
        self.song_map.set_active_section(index)
        if self.section_loop_btn.isChecked():
            self._section_loop_bounds = (section.start, section.end)
        self._seek_to_lyric_row(section.start_row)
        self._update_section_repair_quality()

    def _select_section_list_item(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        if isinstance(index, int):
            self._select_song_section(index)

    def _set_active_section_for_row(self, row: int) -> None:
        for index, section in enumerate(self._song_sections):
            if section.start_row <= row <= section.end_row:
                self.song_map.set_active_section(index)
                if self.section_list.currentRow() != index:
                    self.section_list.setCurrentRow(index)
                return
        self.song_map.set_active_section(-1)

    def merge_selected_section_with_neighbor(self, direction: int) -> None:
        section = self._section_for_selected_row()
        if not section:
            QMessageBox.information(self, "Merge Sections", "Select a lyric section first.")
            return
        index = self._song_sections.index(section)
        neighbor_index = index + (-1 if direction < 0 else 1)
        if not 0 <= neighbor_index < len(self._song_sections):
            QMessageBox.information(self, "Merge Sections", "There is no adjacent section in that direction.")
            return
        neighbor = self._song_sections[neighbor_index]
        if section.kind != neighbor.kind:
            answer = QMessageBox.question(
                self,
                "Merge Different Sections",
                f"Merge {section.label} and {neighbor.label} as one {section.kind} section?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        start_row = min(section.start_row, neighbor.start_row)
        end_row = max(section.end_row, neighbor.end_row)
        self._section_overrides = [
            override
            for override in self._section_overrides
            if override.source != "manual"
            or override.end_row < start_row
            or override.start_row > end_row
        ]
        self._section_overrides.append(SectionOverride(start_row, end_row, section.kind))
        self._section_master = None
        self._sync_section_hints_to_result()
        self._refresh_song_structure()
        merged = self._section_for_row(start_row)
        if merged:
            self._select_song_section(self._song_sections.index(merged))
        self.statusBar().showMessage(
            f"Merged {section.label} and {neighbor.label} into one {section.kind} section"
        )

    def select_next_matching_section(self) -> None:
        current = self._section_for_selected_row()
        if not current:
            QMessageBox.information(self, "Sections", "Select a lyric section first.")
            return
        if current.repeat_group:
            matches = [
                section
                for section in self._song_sections
                if section.repeat_group == current.repeat_group
            ]
        else:
            matches = [section for section in self._song_sections if section.kind == current.kind]
        if len(matches) < 2:
            QMessageBox.information(self, "Sections", "No other matching section was detected.")
            return
        next_section = next((section for section in matches if section.start_row > current.start_row), matches[0])
        self._select_song_section(self._song_sections.index(next_section))
        self.statusBar().showMessage(f"Selected {next_section.label}")

    def use_selected_section_as_master(self) -> None:
        section = self._section_for_selected_row()
        if not section:
            QMessageBox.information(self, "Sections", "Select a lyric section first.")
            return
        self._section_master = section
        self.section_master_label.setText(f"Master: {section.label}")
        self._update_section_repair_quality()
        self.statusBar().showMessage(f"{section.label} is now the repair master")

    def repair_selected_section_from_master(self) -> None:
        target = self._section_for_selected_row()
        source = self._section_master
        if not source or not target:
            QMessageBox.information(self, "Section Repair", "Choose a master section, then select the section to repair.")
            return
        if source.start_row == target.start_row and source.end_row == target.end_row:
            QMessageBox.information(self, "Section Repair", "Select a different destination section.")
            return
        previous = self._lines_from_editor()
        try:
            repair = repair_repeated_section(previous, source, target)
        except ValueError as exc:
            QMessageBox.warning(self, "Section Repair", str(exc))
            return
        source_lines = previous[source.start_row : source.end_row + 1]
        target_lines = previous[target.start_row : target.end_row + 1]
        same_repeat = bool(source.repeat_group and source.repeat_group == target.repeat_group)
        preview = SectionRepairPreviewDialog(
            source.label,
            target.label,
            source_lines,
            target_lines,
            repair,
            same_repeat=same_repeat,
            parent=self,
        )
        if preview.exec() != QDialog.Accepted:
            return
        target_start = target.start_row
        self._set_pending_missing_lines(source_lines, target_lines, repair, target)
        self._set_editor_lines(repair.lines)
        self._sync_current_editor_result()
        self._section_master = None
        self._refresh_song_structure()
        repaired_section = self._section_for_row(target_start)
        if repaired_section:
            self._select_song_section(self._song_sections.index(repaired_section))
        detail = self._section_repair_detail(repair)
        self.statusBar().showMessage(
            f"Repaired {repair.replaced_count} lines at {round(repair.confidence * 100)}% confidence; "
            f"destination timing kept exactly{detail}"
        )

    def repair_all_repeats_from_master(self) -> None:
        source = self._section_master
        if not source:
            QMessageBox.information(self, "Section Repair", "Choose a trusted master section first.")
            return
        if source.repeat_group:
            targets = [
                section
                for section in self._song_sections
                if section.repeat_group == source.repeat_group and section.id != source.id
            ]
        else:
            targets = [
                section
                for section in self._song_sections
                if section.kind == source.kind and section.id != source.id
            ]
        if not targets:
            QMessageBox.information(self, "Section Repair", "No other matching sections were detected.")
            return
        original = self._lines_from_editor()
        source_text = [line.text for line in original[source.start_row : source.end_row + 1]]
        try:
            previews = [replace_section_text(original, target, source_text) for target in targets]
        except ValueError as exc:
            QMessageBox.warning(self, "Section Repair", str(exc))
            return
        lowest_score = min(round(preview.confidence * 100) for preview in previews)
        unmatched_preview = sum(
            preview.unmatched_source + preview.unmatched_target for preview in previews
        )
        answer = QMessageBox.question(
            self,
            "Repair All Repeats",
            f"Apply text from {source.label} to {len(targets)} matching section(s)?\n"
            f"Lowest match: {lowest_score}% | Unmatched lines: {unmatched_preview}\n"
            "Every destination timestamp stays unchanged. Unmatched lines remain for review.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        updated = list(original)
        unmatched_source = 0
        unmatched_target = 0
        repaired_lines = 0
        first_target_row = min(target.start_row for target in targets)
        try:
            for target in sorted(targets, key=lambda item: item.start_row, reverse=True):
                repair = replace_section_text(updated, target, source_text)
                updated = repair.lines
                repaired_lines += repair.replaced_count
                unmatched_source += repair.unmatched_source
                unmatched_target += repair.unmatched_target
        except ValueError as exc:
            QMessageBox.warning(self, "Section Repair", str(exc))
            return
        self._set_editor_lines(updated)
        self._sync_current_editor_result()
        self._section_master = None
        self._refresh_song_structure()
        repaired_section = self._section_for_row(first_target_row)
        if repaired_section:
            self._select_song_section(self._song_sections.index(repaired_section))
        review_count = unmatched_source + unmatched_target
        detail = f"; {review_count} unmatched line(s) need review" if review_count else ""
        self.statusBar().showMessage(f"Repaired {len(targets)} repeats ({repaired_lines} lines){detail}")

    def copy_selected_section_text(self) -> None:
        section = self._section_for_selected_row()
        if not section:
            QMessageBox.information(self, "Sections", "Select a lyric section first.")
            return
        lines = self._lines_from_editor()[section.start_row : section.end_row + 1]
        QApplication.clipboard().setText("\n".join(line.text for line in lines))
        self.statusBar().showMessage(f"Copied {section.label} text")

    def paste_text_into_selected_section(self) -> None:
        section = self._section_for_selected_row()
        if not section:
            QMessageBox.information(self, "Sections", "Select a lyric section first.")
            return
        text_lines = parse_plain_text(QApplication.clipboard().text())
        if not text_lines:
            QMessageBox.information(self, "Sections", "The clipboard does not contain lyric lines.")
            return
        if len(text_lines) != section.line_count:
            answer = QMessageBox.question(
                self,
                "Paste Section",
                f"The clipboard has {len(text_lines)} lines and {section.label} has {section.line_count}.\n"
                "Lyricrafter will map text only onto existing timed rows. No timestamps or rows "
                "will be created. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        previous = self._lines_from_editor()
        try:
            repair = replace_section_text(previous, section, text_lines)
        except ValueError as exc:
            QMessageBox.warning(self, "Paste Section", str(exc))
            return
        start_row = section.start_row
        self._set_editor_lines(repair.lines)
        self._sync_current_editor_result()
        self._refresh_song_structure()
        repaired_section = self._section_for_row(start_row)
        if repaired_section:
            self._select_song_section(self._song_sections.index(repaired_section))
        detail = self._section_repair_detail(repair)
        self.statusBar().showMessage(
            f"Pasted {repair.replaced_count} lines into {section.label}; timing kept exactly{detail}"
        )

    @staticmethod
    def _section_repair_detail(repair: SectionRepair) -> str:
        review_count = repair.unmatched_source + repair.unmatched_target
        if not review_count:
            return ""
        parts = []
        if repair.unmatched_source:
            parts.append(f"{repair.unmatched_source} master line(s) not applied")
        if repair.unmatched_target:
            parts.append(f"{repair.unmatched_target} destination line(s) left unchanged")
        return "; review: " + ", ".join(parts)

    def _update_section_repair_quality(self) -> None:
        if not hasattr(self, "section_repair_quality_label"):
            return
        source = self._section_master
        target = self._section_for_selected_row()
        if not source:
            self.section_repair_quality_label.setText(
                "Select a master and destination to preview repair quality."
            )
            return
        if not target or (source.start_row == target.start_row and source.end_row == target.end_row):
            self.section_repair_quality_label.setText("Select another section to evaluate the repair.")
            return
        try:
            repair = repair_repeated_section(self._lines_from_editor(), source, target)
        except ValueError:
            self.section_repair_quality_label.setText("Repair quality unavailable.")
            return
        score = round(repair.confidence * 100)
        rating = "Strong" if score >= 82 else "Review" if score >= 62 else "Low"
        unmatched = repair.unmatched_source + repair.unmatched_target
        detail = f" | {unmatched} unmatched" if unmatched else " | complete mapping"
        self.section_repair_quality_label.setText(f"Repair match: {score}% | {rating}{detail}")

    def toggle_selected_section_loop(self, enabled: bool) -> None:
        if not enabled:
            self._section_loop_bounds = None
            self.section_loop_btn.setText("Loop Section")
            self.statusBar().showMessage("Section loop disabled")
            return
        section = self._section_for_selected_row()
        if not section:
            self.section_loop_btn.blockSignals(True)
            self.section_loop_btn.setChecked(False)
            self.section_loop_btn.blockSignals(False)
            QMessageBox.information(self, "Section Loop", "Select a song section first.")
            return
        self._section_loop_bounds = (section.start, section.end)
        self.section_loop_btn.setText(f"Looping {section.label}")
        self.player.setPosition(int(section.start * 1000))
        self.player.play()
        self.statusBar().showMessage(
            f"Looping {section.label}: {_format_position(int(section.start * 1000))} - "
            f"{_format_position(int(section.end * 1000))}"
        )

    def _release_loop_seek(self) -> None:
        self._loop_seek_active = False

    def _set_pending_missing_lines(
        self,
        source_lines: list[LyricLine],
        target_lines: list[LyricLine],
        repair: SectionRepair,
        target: LyricSection,
    ) -> None:
        mapped_times = {
            mapping.source_index: target_lines[mapping.target_index].start
            for mapping in repair.mappings
        }
        target_gaps = [
            target_lines[index + 1].start - target_lines[index].start
            for index in range(len(target_lines) - 1)
            if target_lines[index + 1].start > target_lines[index].start
        ]
        typical_gap = sorted(target_gaps)[len(target_gaps) // 2] if target_gaps else 2.0
        pending: list[tuple[str, float]] = []
        for source_index in repair.unmatched_source_indices:
            lower = [index for index in mapped_times if index < source_index]
            upper = [index for index in mapped_times if index > source_index]
            if lower and upper:
                lower_index = max(lower)
                upper_index = min(upper)
                ratio = (source_index - lower_index) / (upper_index - lower_index)
                suggested = mapped_times[lower_index] + ratio * (
                    mapped_times[upper_index] - mapped_times[lower_index]
                )
            elif lower:
                lower_index = max(lower)
                suggested = mapped_times[lower_index] + typical_gap * (source_index - lower_index)
            elif upper:
                upper_index = min(upper)
                suggested = mapped_times[upper_index] - typical_gap * (upper_index - source_index)
            else:
                suggested = target.start + (target.end - target.start) * 0.5
            suggested = max(target.start, min(max(target.start, target.end - 0.05), suggested))
            pending.append((source_lines[source_index].text, suggested))
        self._pending_missing_lines = pending
        self._refresh_missing_line_controls()

    def _refresh_missing_line_controls(self) -> None:
        visible = bool(self._pending_missing_lines)
        self.missing_line_combo.clear()
        for text, suggested in self._pending_missing_lines:
            self.missing_line_combo.addItem(
                f"{_format_position(int(suggested * 1000))}  {text}",
                (text, suggested),
            )
        for widget in (
            self.missing_line_label,
            self.missing_line_combo,
            self.place_missing_suggested_btn,
            self.place_missing_playhead_btn,
        ):
            widget.setVisible(visible)

    def place_missing_line_at_suggested_time(self) -> None:
        self._place_pending_missing_line(use_playhead=False)

    def place_missing_line_at_playhead(self) -> None:
        self._place_pending_missing_line(use_playhead=True)

    def _place_pending_missing_line(self, use_playhead: bool) -> None:
        index = self.missing_line_combo.currentIndex()
        if not 0 <= index < len(self._pending_missing_lines):
            return
        text, suggested = self._pending_missing_lines[index]
        start = self.player.position() / 1000 if use_playhead else suggested
        lines = self._lines_from_editor()
        occupied = {round(line.start, 3) for line in lines}
        while round(start, 3) in occupied:
            start += 0.05
        inserted = LyricLine(start=max(0.0, start), text=text)
        lines.append(inserted)
        lines.sort(key=lambda line: line.start)
        self._set_editor_lines(lines)
        self._sync_current_editor_result()
        self._pending_missing_lines.pop(index)
        self._refresh_missing_line_controls()
        row = lines.index(inserted)
        self.lyric_table.selectRow(row)
        self._seek_to_lyric_row(row)
        source = "playhead" if use_playhead else "suggested AI gap"
        self.statusBar().showMessage(
            f"Placed unmatched line at {_format_position(int(inserted.start * 1000))} using {source}"
        )

    def mark_selected_lines_as_section(self, kind: str | None = None) -> None:
        rows = sorted(index.row() for index in self.lyric_table.selectionModel().selectedRows())
        if not rows:
            QMessageBox.information(self, "Sections", "Select one or more lyric lines first.")
            return
        selected_kind = kind or self.section_kind_combo.currentText()
        start_row, end_row = rows[0], rows[-1]
        self._section_overrides = [
            override
            for override in self._section_overrides
            if override.source != "manual"
            or override.end_row < start_row
            or override.start_row > end_row
        ]
        self._section_overrides.append(SectionOverride(start_row, end_row, selected_kind))
        self._sync_section_hints_to_result()
        self._refresh_song_structure()
        section = self._section_for_row(start_row)
        if section:
            self._select_song_section(self._song_sections.index(section))
        self.statusBar().showMessage(f"Marked lines {start_row + 1}-{end_row + 1} as {selected_kind}")

    def clear_manual_section_labels(self) -> None:
        self._section_overrides = [override for override in self._section_overrides if override.source != "manual"]
        self._sync_section_hints_to_result()
        self._refresh_song_structure()
        self.statusBar().showMessage("Cleared manual section labels")

    def _section_for_row(self, row: int) -> LyricSection | None:
        return next(
            (section for section in self._song_sections if section.start_row <= row <= section.end_row),
            None,
        )

    def _sync_section_hints_to_result(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            return
        self.current_editor_job.result.section_hints = [
            {
                "start_row": override.start_row,
                "end_row": override.end_row,
                "kind": override.kind,
                "source": override.source,
            }
            for override in self._section_overrides
        ]

    def show_editor_context_menu(self, position) -> None:
        item = self.lyric_table.itemAt(position)
        if not item:
            return
        row = item.row()
        selected_rows = {index.row() for index in self.lyric_table.selectionModel().selectedRows()}
        if row not in selected_rows:
            self.lyric_table.selectRow(row)
            selected_rows = {row}
        menu = QMenu(self)
        jump_action = menu.addAction("Jump to Line")
        split_action = menu.addAction("Split Line")
        merge_up_action = menu.addAction("Merge With Above")
        merge_down_action = menu.addAction("Merge With Below")
        merge_selected_action = menu.addAction("Merge Selected")
        space_action = menu.addAction("Space Selected")
        menu.addSeparator()
        section_menu = menu.addMenu("Section")
        select_section_action = section_menu.addAction("Select Entire Section")
        next_match_action = section_menu.addAction("Next Matching Section")
        merge_previous_section_action = section_menu.addAction("Merge With Previous Section")
        merge_next_section_action = section_menu.addAction("Merge With Next Section")
        section_menu.addSeparator()
        master_action = section_menu.addAction("Use as Repair Master")
        repair_action = section_menu.addAction("Repair from Master")
        repair_all_action = section_menu.addAction("Repair All Repeats")
        loop_section_action = section_menu.addAction("Loop Section")
        loop_section_action.setCheckable(True)
        loop_section_action.setChecked(self.section_loop_btn.isChecked())
        section_menu.addSeparator()
        copy_section_action = section_menu.addAction("Copy Section Text")
        paste_section_action = section_menu.addAction("Paste Text, Keep Timing")
        place_missing_action = section_menu.addAction("Place Unmatched at Playhead")
        section_menu.addSeparator()
        undo_section_action = section_menu.addAction("Undo Edit")
        redo_section_action = section_menu.addAction("Redo Edit")
        mark_menu = section_menu.addMenu("Mark Selection As")
        mark_actions: dict[QAction, str] = {}
        for kind in SECTION_KINDS:
            mark_actions[mark_menu.addAction(kind)] = kind
        menu.addSeparator()
        playhead_action = menu.addAction("Start at Playhead")
        delete_action = menu.addAction("Delete Line" if len(selected_rows) <= 1 else "Delete Lines")
        split_action.setEnabled(len(selected_rows) == 1)
        merge_up_action.setEnabled(len(selected_rows) == 1 and row > 0)
        merge_down_action.setEnabled(len(selected_rows) == 1 and row + 1 < self.lyric_table.rowCount())
        merge_selected_action.setEnabled(len(selected_rows) >= 2)
        space_action.setEnabled(len(selected_rows) >= 2)
        selected_section = self._section_for_selected_row()
        selected_section_index = self._song_sections.index(selected_section) if selected_section else -1
        merge_previous_section_action.setEnabled(selected_section_index > 0)
        merge_next_section_action.setEnabled(
            0 <= selected_section_index < len(self._song_sections) - 1
        )
        next_match_action.setEnabled(selected_section is not None)
        repair_action.setEnabled(self._section_master is not None)
        repair_all_action.setEnabled(self._section_master is not None)
        place_missing_action.setEnabled(bool(self._pending_missing_lines))
        undo_section_action.setEnabled(bool(self._undo_stack))
        redo_section_action.setEnabled(bool(self._redo_stack))
        action = menu.exec(self.lyric_table.viewport().mapToGlobal(position))
        if action == jump_action:
            self._seek_to_lyric_row(row)
        elif action == split_action:
            self.lyric_table.selectRow(row)
            self.split_selected_line()
        elif action == merge_up_action:
            self._merge_editor_rows([row - 1, row])
        elif action == merge_down_action:
            self._merge_editor_rows([row, row + 1])
        elif action == merge_selected_action:
            self.merge_selected_lines()
        elif action == space_action:
            self.space_selected_lines()
        elif action == select_section_action:
            section = self._section_for_selected_row()
            if section:
                self._select_song_section(self._song_sections.index(section))
        elif action == next_match_action:
            self.select_next_matching_section()
        elif action == merge_previous_section_action:
            self.merge_selected_section_with_neighbor(-1)
        elif action == merge_next_section_action:
            self.merge_selected_section_with_neighbor(1)
        elif action == master_action:
            self.use_selected_section_as_master()
        elif action == repair_action:
            self.repair_selected_section_from_master()
        elif action == repair_all_action:
            self.repair_all_repeats_from_master()
        elif action == loop_section_action:
            self.section_loop_btn.setChecked(loop_section_action.isChecked())
        elif action == copy_section_action:
            self.copy_selected_section_text()
        elif action == paste_section_action:
            self.paste_text_into_selected_section()
        elif action == place_missing_action:
            self.place_missing_line_at_playhead()
        elif action == undo_section_action:
            self.undo_editor_edit()
        elif action == redo_section_action:
            self.redo_editor_edit()
        elif action in mark_actions:
            self.mark_selected_lines_as_section(mark_actions[action])
        elif action == playhead_action:
            self.lyric_table.selectRow(row)
            self.set_selected_start_to_playhead()
        elif action == delete_action:
            self.delete_selected_editor_lines()

    def _refresh_preview_mode(self) -> None:
        mode = self.display_mode_combo.currentText() if hasattr(self, "display_mode_combo") else "Original + Translation"
        if mode == "Original Only":
            self.preview_original_label.setVisible(True)
            self.preview_translation_label.setVisible(False)
        elif mode == "Translation Only":
            self.preview_original_label.setVisible(False)
            self.preview_translation_label.setVisible(True)
        else:
            self.preview_original_label.setVisible(True)
            self.preview_translation_label.setVisible(True)

    def _row_for_position(self, seconds: float) -> int:
        active = -1
        for row in range(self.lyric_table.rowCount()):
            item = self.lyric_table.item(row, 0)
            if not item:
                continue
            try:
                start = float(item.text())
            except ValueError:
                continue
            if start <= seconds:
                active = row
            else:
                break
        return active

    def nudge_selected_lines(self, delta: float) -> None:
        rows = sorted({index.row() for index in self.lyric_table.selectionModel().selectedRows()})
        if not rows:
            return
        lines = self._lines_from_editor()
        for row in rows:
            line = lines[row]
            lines[row] = LyricLine(
                start=max(0.0, line.start + delta),
                text=line.text,
                translation=line.translation,
            )
        self._set_editor_lines(lines)
        self._restore_editor_selection(rows)
        self._sync_current_editor_result()

    def shift_selected_by_amount(self) -> None:
        self.nudge_selected_lines(self.shift_amount_spin.value())

    def set_selected_start_to_playhead(self) -> None:
        rows = self.lyric_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        lines = self._lines_from_editor()
        line = lines[row]
        lines[row] = LyricLine(
            start=self.player.position() / 1000,
            text=line.text,
            translation=line.translation,
        )
        self._set_editor_lines(lines)
        self.lyric_table.selectRow(row)
        self._sync_current_editor_result()

    def stamp_selected_line_and_advance(self) -> None:
        rows = self.lyric_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        playhead_ms = self.player.position()
        lines = self._lines_from_editor()
        line = lines[row]
        stamped_start = playhead_ms / 1000
        if row > 0:
            stamped_start = max(stamped_start, lines[row - 1].start + 0.05)
        lines[row] = LyricLine(
            start=stamped_start,
            text=line.text,
            translation=line.translation,
        )
        previous_start = stamped_start
        for following in range(row + 1, len(lines)):
            if lines[following].start > previous_start:
                break
            following_line = lines[following]
            previous_start += 0.05
            lines[following] = LyricLine(
                start=previous_start,
                text=following_line.text,
                translation=following_line.translation,
            )
        self._set_editor_lines(lines)
        next_row = min(row + 1, self.lyric_table.rowCount() - 1)
        self._syncing_table_selection = True
        try:
            self.lyric_table.selectRow(next_row)
        finally:
            self._syncing_table_selection = False
        self.waveform.set_selected_rows({next_row})
        self.player.setPosition(playhead_ms)
        self._sync_current_editor_result()
        self.statusBar().showMessage(f"Stamped line {row + 1}; ready for line {next_row + 1}")

    def sort_editor_lines_by_time(self) -> None:
        lines = sorted(self._lines_from_editor(), key=lambda line: line.start)
        self._section_overrides.clear()
        self._section_master = None
        self._sync_section_hints_to_result()
        self._set_editor_lines(lines)
        self._sync_current_editor_result()
        self.statusBar().showMessage("Lyric lines sorted by timestamp")

    def split_selected_line(self) -> None:
        rows = self.lyric_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        start_item = self.lyric_table.item(row, 0)
        text_item = self.lyric_table.item(row, 1)
        if not start_item or not text_item:
            return
        text = text_item.text().strip()
        words = text.split()
        if len(words) < 2:
            return
        midpoint = len(words) // 2
        first = " ".join(words[:midpoint])
        second = " ".join(words[midpoint:])
        start = float(start_item.text())
        lines = self._lines_from_editor()
        original = lines[row]
        next_start = lines[row + 1].start if row + 1 < len(lines) else start + 2.0
        split_start = min(next_start - 0.05, start + max(0.45, (next_start - start) / 2))
        lines[row] = LyricLine(start=start, text=first, translation=original.translation)
        lines.insert(row + 1, LyricLine(start=max(start + 0.05, split_start), text=second))
        self._set_editor_lines(lines)
        self.lyric_table.selectRow(row + 1)
        self._sync_current_editor_result()

    def merge_selected_lines(self) -> None:
        rows = sorted((index.row() for index in self.lyric_table.selectionModel().selectedRows()))
        self._merge_editor_rows(rows)

    def _merge_editor_rows(self, rows: list[int]) -> None:
        rows = sorted({row for row in rows if 0 <= row < self.lyric_table.rowCount()})
        if len(rows) < 2:
            return
        first_row = rows[0]
        lines = self._lines_from_editor()
        if first_row >= len(lines):
            return
        parts: list[str] = []
        translations: list[str] = []
        for row in rows:
            if row >= len(lines):
                continue
            if lines[row].text.strip():
                parts.append(lines[row].text.strip())
            if lines[row].translation and lines[row].translation.strip():
                translations.append(lines[row].translation.strip())
        merged = LyricLine(
            start=lines[first_row].start,
            text=" ".join(parts),
            translation=" ".join(translations) or None,
        )
        updated = [line for index, line in enumerate(lines) if index not in rows]
        updated.insert(first_row, merged)
        self._set_editor_lines(updated)
        self.lyric_table.selectRow(min(first_row, self.lyric_table.rowCount() - 1))
        self._sync_current_editor_result()
        self.statusBar().showMessage("Merged lyric lines")

    def delete_selected_editor_lines(self) -> None:
        rows = sorted({index.row() for index in self.lyric_table.selectionModel().selectedRows()})
        if not rows:
            return
        lines = [line for index, line in enumerate(self._lines_from_editor()) if index not in rows]
        next_row = min(rows[0], max(0, len(lines) - 1))
        self._set_editor_lines(lines)
        if lines:
            self.lyric_table.selectRow(next_row)
            self._seek_to_lyric_row(next_row)
        else:
            self.preview_original_label.setText("No lyric loaded")
            self.preview_translation_label.setText("")
            self.now_playing_label.setText("No lyric loaded")
        self._sync_current_editor_result()
        self.statusBar().showMessage("Deleted lyric line" if len(rows) == 1 else f"Deleted {len(rows)} lyric lines")

    def space_selected_lines(self) -> None:
        rows = sorted({index.row() for index in self.lyric_table.selectionModel().selectedRows()})
        if len(rows) < 2:
            return
        lines = self._lines_from_editor()
        first = rows[0]
        last = rows[-1]
        if last >= len(lines):
            return
        start = lines[first].start
        end = lines[last].start
        if end <= start:
            end = start + (len(rows) - 1) * 1.5
        step = (end - start) / max(1, len(rows) - 1)
        for offset, row in enumerate(rows):
            if row < len(lines):
                lines[row] = LyricLine(start=start + step * offset, text=lines[row].text, translation=lines[row].translation)
        self._set_editor_lines(lines)
        for row in rows:
            if row < self.lyric_table.rowCount():
                self.lyric_table.selectRow(row)
        self._sync_current_editor_result()
        self.statusBar().showMessage("Spaced selected lyric lines")

    def translate_lines_placeholder(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            QMessageBox.information(self, "Translation", "Load a completed lyric job first.")
            return
        if self.translation_worker and self.translation_worker.isRunning():
            QMessageBox.information(self, "Translation", "Translation is already running.")
            return

        texts: list[str] = []
        row_indexes: list[int] = []
        for row in range(self.lyric_table.rowCount()):
            item = self.lyric_table.item(row, 1)
            if item and item.text().strip():
                texts.append(item.text().strip())
                row_indexes.append(row)
        if not texts:
            return

        source_name = self.source_language_combo.currentText()
        if source_name == "Auto detect from transcription":
            source_lang = nllb_code_for_iso(self.current_editor_job.result.detected_language)
        else:
            source_lang = nllb_code_for_name(source_name)
        target_lang = nllb_code_for_name(self.target_language_combo.currentText())
        engine = self.translation_engine_combo.currentText()
        if engine == "DeepL API - Cloud Quality":
            QMessageBox.information(
                self,
                "DeepL API",
                "DeepL support is planned as an optional cloud translator. Use an NLLB local engine for now.",
            )
            return
        if engine == "Whisper Translate - English Only":
            QMessageBox.information(
                self,
                "Whisper Translate",
                "Whisper translation runs during transcription and only targets English. Use NLLB local for bilingual line translation.",
            )
            return
        model_id = model_id_for_engine(engine)

        self._translation_rows = row_indexes
        self.translation_worker = TranslationWorker(
            texts,
            source_lang,
            target_lang,
            model_id=model_id,
            manager=self.model_manager,
        )
        self.translation_worker.progress.connect(self._on_translation_progress)
        self.translation_worker.failed.connect(self._on_translation_failed)
        self.translation_worker.finished_translations.connect(self._on_translation_finished)
        self.translation_worker.start()

    def cleanup_editor_lines(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            QMessageBox.information(self, "Cleanup", "Load a completed lyric job first.")
            return
        cleaned = cleanup_lyric_lines(self._lines_from_editor())
        self._set_editor_lines(cleaned)
        self.current_editor_job.result.lines[:] = cleaned
        self.statusBar().showMessage("Lyric cleanup complete")

    def merge_short_editor_lines(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            QMessageBox.information(self, "Cleanup", "Load a completed lyric job first.")
            return
        lines = self._lines_from_editor()
        merged: list[LyricLine] = []
        index = 0
        changed = 0
        while index < len(lines):
            line = lines[index]
            words = line.text.split()
            if 0 < len(words) <= 2 and index + 1 < len(lines) and lines[index + 1].start - line.start <= 2.4:
                next_line = lines[index + 1]
                merged.append(
                    LyricLine(
                        start=line.start,
                        text=f"{line.text.strip()} {next_line.text.strip()}".strip(),
                        translation=_join_optional(line.translation, next_line.translation),
                    )
                )
                index += 2
                changed += 1
                continue
            merged.append(line)
            index += 1
        self._set_editor_lines(merged)
        self._sync_current_editor_result()
        self.statusBar().showMessage(f"Merged {changed} short fragment(s)")

    def _on_translation_progress(self, percent: int, message: str) -> None:
        self.header_status.setText(f"{message} ({percent}%)")
        self.statusBar().showMessage(f"{message} ({percent}%)")

    def _on_translation_failed(self, message: str) -> None:
        self.header_status.setText("Translation failed")
        self.statusBar().showMessage(message)
        QMessageBox.critical(self, "Translation failed", message)

    def _on_translation_finished(self, translations: list[str]) -> None:
        rows = getattr(self, "_translation_rows", [])
        lines = self._lines_from_editor()
        for row, translation in zip(rows, translations):
            if 0 <= row < len(lines):
                line = lines[row]
                lines[row] = LyricLine(start=line.start, text=line.text, translation=translation)
        self._set_editor_lines(lines)
        if self.current_editor_job and self.current_editor_job.result:
            updated_lines = self._lines_from_editor()
            self.current_editor_job.result.lines[:] = updated_lines
            self.editor_text.setPlainText(render_txt(updated_lines))
            self._refresh_translation_column_visibility(updated_lines)
        self.header_status.setText("Translation complete")
        self.statusBar().showMessage("Translation complete")
        self._highlight_current_lyric(max(0, self.player.position() / 1000))

    def _lines_from_editor(self) -> list[LyricLine]:
        lines: list[LyricLine] = []
        for row in range(self.lyric_table.rowCount()):
            start_item = self.lyric_table.item(row, 0)
            text_item = self.lyric_table.item(row, 1)
            translation_item = self.lyric_table.item(row, 2)
            if not start_item or not text_item:
                continue
            try:
                start = float(start_item.text())
            except ValueError:
                start = 0.0
            lines.append(
                LyricLine(
                    start=start,
                    text=text_item.text(),
                    translation=translation_item.text() if translation_item else None,
                )
            )
        return lines

    def _set_editor_lines(
        self,
        lines: list[LyricLine],
        *,
        reset_history: bool = False,
        record_history: bool = True,
    ) -> None:
        previous = list(self._last_editor_lines)
        normalized = list(lines)
        if not reset_history and previous and len(previous) != len(normalized):
            self._section_overrides.clear()
            self._section_master = None
            self._sync_section_hints_to_result()
        self._editor_updating = True
        try:
            self.lyric_table.setRowCount(len(normalized))
            for row, line in enumerate(normalized):
                self.lyric_table.setItem(row, 0, QTableWidgetItem(f"{line.start:.2f}"))
                self.lyric_table.setItem(row, 1, QTableWidgetItem(line.text))
                self.lyric_table.setItem(row, 2, QTableWidgetItem(line.translation or ""))
                self.lyric_table.setRowHeight(row, 46)
        finally:
            self._editor_updating = False
        self.editor_text.setPlainText(render_txt(normalized))
        self._refresh_translation_column_visibility(normalized)
        self.waveform.set_lines(normalized)
        if reset_history:
            self._undo_stack.clear()
            self._redo_stack.clear()
        elif record_history and previous != normalized:
            self._undo_stack.append(previous)
            self._redo_stack.clear()
        self._last_editor_lines = normalized
        self._update_undo_buttons()
        self._refresh_song_structure(normalized)

    def _sync_current_editor_result(self) -> None:
        if self.current_editor_job and self.current_editor_job.result:
            lines = self._lines_from_editor()
            self.current_editor_job.result.lines[:] = lines
            self.editor_text.setPlainText(render_txt(lines))
            self._refresh_translation_column_visibility(lines)
            self.waveform.set_lines(lines)
            self._last_editor_lines = list(lines)

    def _on_editor_item_changed(self, _item: QTableWidgetItem) -> None:
        if self._editor_updating:
            return
        previous = list(self._last_editor_lines)
        self._record_editor_change(previous)
        self._structure_refresh_timer.start()

    def _record_editor_change(self, previous: list[LyricLine]) -> None:
        current = self._lines_from_editor()
        if previous == current:
            return
        self._undo_stack.append(list(previous))
        self._redo_stack.clear()
        self._last_editor_lines = list(current)
        self._sync_current_editor_result()
        self._update_undo_buttons()

    def undo_editor_edit(self) -> None:
        if not self._undo_stack:
            return
        current = self._lines_from_editor()
        target = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._set_editor_lines(target, record_history=False)
        self._sync_current_editor_result()
        self._pending_missing_lines.clear()
        self._refresh_missing_line_controls()
        self._update_undo_buttons()
        self.statusBar().showMessage("Undid lyric edit")

    def redo_editor_edit(self) -> None:
        if not self._redo_stack:
            return
        current = self._lines_from_editor()
        target = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._set_editor_lines(target, record_history=False)
        self._sync_current_editor_result()
        self._update_undo_buttons()
        self.statusBar().showMessage("Redid lyric edit")

    def _update_undo_buttons(self) -> None:
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(bool(self._undo_stack))
            self.redo_btn.setEnabled(bool(self._redo_stack))

    def _restore_editor_selection(self, rows: list[int]) -> None:
        self.lyric_table.clearSelection()
        for row in rows:
            if 0 <= row < self.lyric_table.rowCount():
                self.lyric_table.selectRow(row)

    def _refresh_translation_column_visibility(self, lines: list[LyricLine] | None = None) -> None:
        lines = lines if lines is not None else self._lines_from_editor()
        has_translation = any((line.translation or "").strip() for line in lines)
        self.lyric_table.setColumnHidden(2, not has_translation)

    def save_editor_project(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            QMessageBox.information(self, "Project", "Load a completed lyric job first.")
            return
        self._sync_current_editor_result()
        default_path = default_project_path(self.current_editor_job.source_path)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Lyricrafter project",
            str(default_path),
            "Lyricrafter project (*.lyricrafter.json);;JSON files (*.json)",
        )
        if not path:
            return
        saved_path = save_project(self.current_editor_job, Path(path))
        self.statusBar().showMessage(f"Saved project {saved_path.name}")

    def open_project_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Lyricrafter project",
            "",
            "Lyricrafter project (*.lyricrafter.json);;JSON files (*.json)",
        )
        if not path:
            return
        try:
            job = load_project(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Project", f"Could not open project: {exc}")
            return
        job.status = JobStatus.COMPLETE
        job.progress = 100
        existing = next((item for item in self.jobs if item.source_path == job.source_path), None)
        if existing:
            existing.result = job.result
            existing.status = job.status
            existing.progress = job.progress
            existing.message = job.message
            job = existing
        else:
            self.jobs.append(job)
        self._refresh_queue()
        self.load_job_in_editor(job)
        self.statusBar().showMessage(f"Opened project {Path(path).name}")

    def run_quality_check(self) -> None:
        lines = self._lines_from_editor()
        issues = check_lyrics_quality(lines)
        self._show_quality_issues(issues)
        self.statusBar().showMessage("Quality check complete")

    def _show_quality_issues(self, issues: list[QualityIssue], notes: list[str] | None = None) -> None:
        if not hasattr(self, "quality_list"):
            return
        self.quality_list.clear()
        score = quality_score(issues)
        self.quality_score_label.setText(f"{score}  {quality_label(score)}")
        colors = {
            "Error": QColor("#ff879d"),
            "Warning": QColor("#ffc66d"),
            "Review": QColor("#8fc5ff"),
            "Pass": QColor("#72d6a0"),
        }
        for issue in issues:
            prefix = f"Line {issue.row}  " if issue.row is not None else ""
            item = QListWidgetItem(f"{prefix}{issue.message}")
            item.setData(Qt.UserRole, issue.row - 1 if issue.row is not None else -1)
            item.setData(Qt.UserRole + 1, issue.severity)
            item.setForeground(colors.get(issue.severity, QColor("#c3cfdd")))
            item.setToolTip("Click to jump to this lyric line" if issue.row is not None else issue.message)
            self.quality_list.addItem(item)
        for note in notes or []:
            if not note.strip():
                continue
            item = QListWidgetItem(note.strip())
            item.setData(Qt.UserRole, -1)
            item.setForeground(colors["Review"])
            self.quality_list.addItem(item)

    def _activate_quality_item(self, item: QListWidgetItem) -> None:
        stored_row = item.data(Qt.UserRole)
        row = int(stored_row) if stored_row is not None else -1
        if 0 <= row < self.lyric_table.rowCount():
            self.lyric_table.selectRow(row)
            self._seek_to_lyric_row(row)

    def save_editor_outputs(self) -> None:
        if not self.current_editor_job or not self.current_editor_job.result:
            QMessageBox.information(self, "Editor", "Load a completed job first.")
            return
        lines = self._lines_from_editor()
        result = self.current_editor_job.result
        result.lines[:] = lines
        self._write_result_outputs(result)
        if any((line.translation or "").strip() for line in lines):
            if self.export_lrc_enabled:
                translated_lrc = result.lrc_path.with_name(f"{result.lrc_path.stem}.translated.lrc")
                bilingual_lrc = result.lrc_path.with_name(f"{result.lrc_path.stem}.bilingual.lrc")
                translated_lrc.write_text(render_translated_lrc(lines), encoding="utf-8")
                bilingual_lrc.write_text(render_bilingual_lrc(lines), encoding="utf-8")
            if self.export_txt_enabled:
                bilingual_txt = result.txt_path.with_name(f"{result.txt_path.stem}.bilingual.txt")
                bilingual_txt.write_text(render_bilingual_txt(lines), encoding="utf-8")
        self.editor_text.setPlainText(render_txt(lines))
        self.statusBar().showMessage(f"Saved {', '.join(self._result_output_names(result))}")

    def _write_result_outputs(self, result: JobResult) -> None:
        lines = result.lines
        self._save_output_settings()
        if self.export_lrc_enabled:
            result.lrc_path.write_text(render_lrc(lines), encoding="utf-8")
        if self.export_txt_enabled:
            result.txt_path.write_text(render_txt(lines), encoding="utf-8")
        if self.export_srt_enabled:
            result.srt_path = result.srt_path or result.lrc_path.with_suffix(".srt")
            result.srt_path.write_text(render_srt(lines), encoding="utf-8")
        if self.export_vtt_enabled:
            result.vtt_path = result.vtt_path or result.lrc_path.with_suffix(".vtt")
            result.vtt_path.write_text(render_vtt(lines), encoding="utf-8")

    def _refresh_model_table(self) -> None:
        models = self.catalog.list_models("whisper") + self.catalog.list_models("whisper_cpp")
        self.model_table.setRowCount(len(models))
        for row, model in enumerate(models):
            managed = self.model_manager.is_installed(model.id, model.backend)
            shared = (
                model.backend == "faster-whisper"
                and self.model_manager.resolved_faster_whisper_path(model.id) is not None
            )
            status = "Installed" if managed else "Shared cache" if shared else "Available"
            values = [
                model.id,
                model.name,
                model.recommended_for,
                model.family,
                model.backend,
                model.size,
                status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, model.id)
                self.model_table.setItem(row, column, item)

    def download_selected_model(self) -> None:
        rows = self.model_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Models", "Select a faster-whisper model to download.")
            return
        row = rows[0].row()
        backend = self.model_table.item(row, 4).text()
        model_id = self.model_table.item(row, 0).text()
        self._start_model_download([model_id], backend)

    def download_all_faster_whisper(self) -> None:
        model_ids = [model.id for model in self.catalog.list_models("whisper") if model.backend == "faster-whisper"]
        if not model_ids:
            return
        self._start_model_download(model_ids, "faster-whisper")

    def delete_selected_model(self) -> None:
        rows = self.model_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Models", "Select a model to delete.")
            return
        row = rows[0].row()
        backend = self.model_table.item(row, 4).text()
        model_id = self.model_table.item(row, 0).text()
        if not self.model_manager.is_installed(model_id, backend):
            QMessageBox.information(self, "Models", f"{model_id} is not installed.")
            return
        answer = QMessageBox.question(
            self,
            "Delete Model",
            f"Delete {model_id} from local model storage? It can be downloaded again later.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            deleted = self.model_manager.delete_model(model_id, backend)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Delete Model", str(exc))
            return
        self._refresh_model_table()
        self.statusBar().showMessage(f"Deleted model: {model_id}" if deleted else f"Model not found: {model_id}")

    def _start_model_download(self, model_ids: list[str], backend: str) -> None:
        if self.download_worker and self.download_worker.isRunning():
            QMessageBox.information(self, "Models", "A model download is already running.")
            return
        self.model_download_progress.setValue(0)
        self.model_download_label.setText("Preparing model download")
        self._set_workspace_page(2)
        self.download_worker = ModelDownloadWorker(model_ids, backend=backend, manager=self.model_manager)
        self.download_worker.progress.connect(self._on_model_download_progress)
        self.download_worker.failed.connect(self._on_model_download_failed)
        self.download_worker.finished_path.connect(self._on_model_download_finished_path)
        self.download_worker.all_finished.connect(self._on_model_download_all_finished)
        self.download_worker.start()

    def _on_model_download_progress(self, percent: int, message: str) -> None:
        self.model_download_progress.setValue(percent)
        self.model_download_label.setText(message)
        self.header_status.setText(message)
        self.statusBar().showMessage(message)

    def _on_model_download_failed(self, message: str) -> None:
        self.model_download_label.setText(f"Download failed: {message}")
        self.header_status.setText("Download failed")
        self.statusBar().showMessage(message)
        QMessageBox.critical(self, "Download failed", message)

    def _on_model_download_finished_path(self, path: str) -> None:
        self.model_download_label.setText(f"Downloaded to {path}")
        self.statusBar().showMessage(f"Downloaded to {path}")

    def _on_model_download_all_finished(self) -> None:
        self.model_download_progress.setValue(100)
        self.model_download_label.setText("All model downloads completed")
        self.header_status.setText("Ready")
        self.statusBar().showMessage("All model downloads completed")
        self._refresh_model_table()

    def open_model_folder(self) -> None:
        open_in_file_manager(self.model_manager.model_dir)

    def install_nvidia_runtime(self) -> None:
        if self.nvidia_runtime_worker and self.nvidia_runtime_worker.isRunning():
            return
        answer = QMessageBox.question(
            self,
            "Install NVIDIA Support",
            "Download about 1.2 GB of NVIDIA CUDA libraries for Whisper transcription?\n\n"
            "This is optional and requires a compatible NVIDIA GPU and current driver.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.nvidia_runtime_progress.setValue(0)
        self.install_nvidia_btn.setEnabled(False)
        self.remove_nvidia_btn.setEnabled(False)
        self.nvidia_runtime_worker = NvidiaRuntimeWorker(self.nvidia_runtime_manager)
        self.nvidia_runtime_worker.progress.connect(self._on_nvidia_runtime_progress)
        self.nvidia_runtime_worker.failed.connect(self._on_nvidia_runtime_failed)
        self.nvidia_runtime_worker.installed.connect(self._on_nvidia_runtime_installed)
        self.nvidia_runtime_worker.start()

    def remove_nvidia_runtime(self) -> None:
        answer = QMessageBox.question(
            self,
            "Remove NVIDIA Support",
            "Remove the downloaded NVIDIA runtime? Whisper will use CPU after Lyricrafter restarts.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            removed = self.nvidia_runtime_manager.uninstall()
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Remove NVIDIA Support",
                f"The runtime is currently in use. Close Lyricrafter and remove it after restarting.\n\n{exc}",
            )
            return
        self.nvidia_runtime_progress.setValue(0)
        self._refresh_nvidia_runtime_controls()
        self.statusBar().showMessage("NVIDIA support removed" if removed else "NVIDIA support is not installed")

    def _on_nvidia_runtime_progress(self, percent: int, message: str) -> None:
        self.nvidia_runtime_progress.setValue(percent)
        self.nvidia_runtime_label.setText(message)
        self.header_status.setText(message)
        self.statusBar().showMessage(message)

    def _on_nvidia_runtime_failed(self, message: str) -> None:
        self.header_status.setText("NVIDIA install failed")
        self._refresh_nvidia_runtime_controls()
        self.nvidia_runtime_label.setText(f"NVIDIA install failed: {message}")
        QMessageBox.critical(self, "NVIDIA install failed", message)

    def _on_nvidia_runtime_installed(self, path: str) -> None:
        self.nvidia_runtime_progress.setValue(100)
        self.header_status.setText("Restart to activate NVIDIA support")
        self._refresh_nvidia_runtime_controls()
        self.nvidia_runtime_label.setText("NVIDIA support installed. Restart Lyricrafter to activate it.")
        QMessageBox.information(
            self,
            "NVIDIA Support",
            f"NVIDIA Whisper acceleration was installed to:\n{path}\n\nRestart Lyricrafter before processing audio.",
        )

    def _refresh_nvidia_runtime_controls(self) -> None:
        installed = self.nvidia_runtime_manager.installed
        supported = self.nvidia_runtime_manager.supported
        running = bool(self.nvidia_runtime_worker and self.nvidia_runtime_worker.isRunning())
        self.install_nvidia_btn.setEnabled(supported and not installed and not running)
        self.remove_nvidia_btn.setEnabled(supported and installed and not running)
        if not running:
            self.nvidia_runtime_label.setText(self.nvidia_runtime_manager.status_text())

    def choose_model_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose model folder", str(self.model_manager.model_dir))
        if not folder:
            return
        self.model_manager = ModelManager(Path(folder))
        self.engine.set_model_manager(self.model_manager)
        self.model_dir_label.setText(folder)
        self.db.set_setting("model_dir", folder)

    def _refresh_history(self) -> None:
        rows = self.db.list_history()
        self.history_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            outputs = ", ".join(item for item in [row["lrc_path"], row["txt_path"]] if item)
            values = [row["updated_at"], row["source_path"], row["status"], row["message"] or "", outputs]
            for column, value in enumerate(values):
                self.history_table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def clear_history(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear History",
            "Clear all job history? This does not delete generated lyric files.",
        )
        if answer != QMessageBox.Yes:
            return
        self.db.clear_history()
        self._refresh_history()
        self.statusBar().showMessage("History cleared")


class SectionRepairPreviewDialog(QDialog):
    def __init__(
        self,
        source_label: str,
        target_label: str,
        source_lines: list[LyricLine],
        target_lines: list[LyricLine],
        repair: SectionRepair,
        *,
        same_repeat: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Repair Preview")
        self.resize(920, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(f"{source_label}  to  {target_label}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        score = round(repair.confidence * 100)
        rating = "Strong" if score >= 82 else "Review" if score >= 62 else "Low"
        summary = QLabel(
            f"{score}% {rating} match | {repair.replaced_count} mapped | "
            f"{repair.unmatched_source} need timing | {repair.unmatched_target} kept unchanged"
        )
        summary.setObjectName("Muted")
        layout.addWidget(summary)

        notice_text = "Destination timestamps and existing row positions will remain unchanged."
        if not same_repeat:
            notice_text += " These sections were not detected as the same repeat; review every mapping."
        if score < 62:
            notice_text += " This is a low-confidence repair."
        notice = QLabel(notice_text)
        notice.setWordWrap(True)
        layout.addWidget(notice)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Action", "Master", "Destination", "Time", "Match"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        self.mapping_table = table

        mappings_by_target = {mapping.target_index: mapping for mapping in repair.mappings}
        rows: list[tuple[str, str, str, str, str]] = []
        for target_index, target_line in enumerate(target_lines):
            mapping = mappings_by_target.get(target_index)
            if mapping:
                rows.append(
                    (
                        "Replace",
                        source_lines[mapping.source_index].text,
                        target_line.text,
                        _format_position(int(target_line.start * 1000)),
                        f"{round(mapping.similarity * 100)}%",
                    )
                )
            else:
                rows.append(
                    (
                        "Keep",
                        "-",
                        target_line.text,
                        _format_position(int(target_line.start * 1000)),
                        "-",
                    )
                )
        for source_index in repair.unmatched_source_indices:
            rows.append(("Needs timing", source_lines[source_index].text, "-", "-", "-"))

        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    if value == "Replace":
                        item.setForeground(QColor("#65c8a5"))
                    elif value == "Needs timing":
                        item.setForeground(QColor("#f0b45c"))
                table.setItem(row_index, column, item)
            table.setRowHeight(row_index, 38)
        layout.addWidget(table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply Safe Repair")
        apply_btn.setObjectName("PrimaryButton")
        apply_btn.clicked.connect(self.accept)
        self.apply_btn = apply_btn
        actions.addWidget(cancel_btn)
        actions.addWidget(apply_btn)
        layout.addLayout(actions)


class LyricsSourcesDialog(QDialog):
    def __init__(self, enabled_sources: dict[str, bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lyrics Sources")
        self.resize(820, 620)
        self._candidates: list[LyricCandidate] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.lrclib_check = QCheckBox("LRCLIB")
        self.lrclib_check.setChecked(enabled_sources.get("lrclib", True))
        self.local_check = QCheckBox("Local")
        self.local_check.setChecked(enabled_sources.get("local", True))
        self.captions_check = QCheckBox("Captions")
        self.captions_check.setChecked(enabled_sources.get("captions", True))
        self.synced_check = QCheckBox("Synced")
        self.synced_check.setChecked(enabled_sources.get("synced", True))
        self.synced_check.setToolTip("Search syncedlyrics providers. Genius is plain text and uses AI timing when applied.")
        self.experimental_check = QCheckBox("Exp.")
        self.experimental_check.setChecked(enabled_sources.get("experimental", False))
        self.experimental_check.setToolTip("Experimental sources are off by default.")
        for checkbox in (
            self.lrclib_check,
            self.local_check,
            self.captions_check,
            self.synced_check,
            self.experimental_check,
        ):
            top.addWidget(checkbox)
        top.addStretch(1)
        self.search_btn = QPushButton("Search")
        top.addWidget(self.search_btn)
        layout.addLayout(top)

        search_box = QGroupBox("Search")
        search_form = QFormLayout(search_box)
        search_form.setContentsMargins(12, 14, 12, 10)
        search_form.setVerticalSpacing(8)
        self.search_title = QLineEdit()
        self.search_title.setPlaceholderText("Track title or manual search text")
        self.search_artist = QLineEdit()
        self.search_artist.setPlaceholderText("Artist")
        self.search_album = QLineEdit()
        self.search_album.setPlaceholderText("Album optional")
        self.sync_mode_combo = QComboBox()
        self.sync_mode_combo.addItems(["Strict", "Balanced", "Flexible"])
        self.sync_mode_combo.setCurrentText("Strict")
        self.sync_mode_combo.setToolTip("Controls how aggressively plain lyrics, including Genius, are matched to AI timing.")
        search_form.addRow("Title", self.search_title)
        search_form.addRow("Artist", self.search_artist)
        search_form.addRow("Album", self.search_album)
        search_form.addRow("AI Sync", self.sync_mode_combo)
        layout.addWidget(search_box)

        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("Muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Source", "Type", "Match", "Lang", "Use"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        layout.addWidget(self.table, 1)

        paste_label = QLabel("Paste")
        paste_label.setObjectName("Muted")
        layout.addWidget(paste_label)
        self.paste_box = QTextEdit()
        self.paste_box.setMaximumHeight(120)
        self.paste_box.setPlaceholderText("Paste lyrics here to align them with AI timing")
        self.paste_box.textChanged.connect(self._refresh_paste_state)
        layout.addWidget(self.paste_box)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(95)
        self.preview.setPlaceholderText("Preview selected lyrics")
        layout.addWidget(self.preview)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_btn = QPushButton("Preview")
        self.save_txt_btn = QPushButton("Save TXT")
        self.save_txt_btn.setToolTip("Save the selected provider lyrics as a plain text file beside the source audio.")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("PrimaryButton")
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(self.preview_btn)
        actions.addWidget(self.save_txt_btn)
        actions.addWidget(self.apply_btn)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    def enabled_sources(self) -> dict[str, bool]:
        return {
            "lrclib": self.lrclib_check.isChecked(),
            "local": self.local_check.isChecked(),
            "captions": self.captions_check.isChecked(),
            "synced": self.synced_check.isChecked(),
            "experimental": self.experimental_check.isChecked(),
        }

    def search_values(self) -> dict[str, str]:
        return {
            "title": self.search_title.text().strip(),
            "artist": self.search_artist.text().strip(),
            "album": self.search_album.text().strip(),
        }

    def set_search_values(self, title: str, artist: str, album: str) -> None:
        self.search_title.setText(title)
        self.search_artist.setText(artist)
        self.search_album.setText(album)

    def sync_threshold(self) -> float:
        mode = self.sync_mode_combo.currentText()
        if mode == "Strict":
            return 0.68
        if mode == "Flexible":
            return 0.48
        return 0.56

    def set_busy(self, busy: bool, message: str) -> None:
        self.search_btn.setEnabled(not busy)
        self.apply_btn.setEnabled(not busy)
        self.preview_btn.setEnabled(not busy)
        self.save_txt_btn.setEnabled(not busy)
        self.progress_label.setText(message)
        if busy:
            self.progress_bar.setValue(0)

    def set_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.progress_label.setText(message)

    def set_candidates(self, candidates: list[LyricCandidate]) -> None:
        self._candidates = candidates
        self.table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            values = [
                candidate.provider,
                candidate.kind,
                f"{candidate.confidence}%",
                candidate.language or "-",
                _candidate_label(candidate),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 38)
        if candidates:
            self.table.selectRow(0)
        self.preview.clear()

    def selected_candidate(self) -> LyricCandidate | None:
        if self.pasted_lyrics():
            return None
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._candidates):
            return self._candidates[row]
        return None

    def set_preview(self, text: str) -> None:
        self.preview.setPlainText(text.strip() or "No lyric text available.")

    def pasted_lyrics(self) -> str:
        return self.paste_box.toPlainText().strip()

    def _refresh_paste_state(self) -> None:
        has_paste = bool(self.pasted_lyrics())
        if has_paste:
            self.table.clearSelection()
            self.progress_label.setText("Pasted lyrics ready")


class BatchLyricsSourcesDialog(QDialog):
    def __init__(self, jobs: list[LyricJob], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch Lyrics Sources")
        self.resize(920, 540)
        self._jobs = {job.id: job for job in jobs}
        self._candidates: dict[str, list[LyricCandidate]] = {job.id: [] for job in jobs}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Batch Sources")
        title.setObjectName("PanelTitle")
        hint = QLabel("Find provider lyrics for the queue. Synced sources save directly. Plain sources follow the selected mode.")
        hint.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(hint)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_label = QLabel("Plain")
        mode_label.setObjectName("Muted")
        self.plain_mode_combo = QComboBox()
        self.plain_mode_combo.addItems(["Save TXT only", "Use AI sync", "Skip plain"])
        self.plain_mode_combo.setToolTip("Plain sources like Genius have no timing. Save TXT only avoids AI; Use AI sync runs AI timing when synced output is needed.")
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.plain_mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("Muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)

        self.table = QTableWidget(len(jobs), 5)
        self.table.setHorizontalHeaderLabels(["Track", "Best", "Type", "Match", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        for row, job in enumerate(jobs):
            self.table.setItem(row, 0, QTableWidgetItem(job.source_path.name))
            self.table.item(row, 0).setData(Qt.UserRole, job.id)
            self.table.setItem(row, 1, QTableWidgetItem("Searching..."))
            self.table.setItem(row, 2, QTableWidgetItem("-"))
            self.table.setItem(row, 3, QTableWidgetItem("-"))
            self.table.setItem(row, 4, QTableWidgetItem("Pending"))
            self.table.setRowHeight(row, 38)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_txt_btn = QPushButton("Save TXT")
        self.save_txt_btn.setToolTip("Save best provider text beside each source audio.")
        self.apply_sources_btn = QPushButton("Apply / Save")
        self.apply_sources_btn.setObjectName("PrimaryButton")
        self.apply_sources_btn.setToolTip("Apply synced sources and save selected outputs. Plain sources follow the Plain mode above.")
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.save_txt_btn)
        actions.addWidget(self.apply_sources_btn)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    def set_busy(self, busy: bool, message: str) -> None:
        self.apply_sources_btn.setEnabled(not busy)
        self.save_txt_btn.setEnabled(not busy)
        self.plain_mode_combo.setEnabled(not busy)
        self.progress_label.setText(message)
        if busy:
            self.progress_bar.setValue(0)

    def plain_mode(self) -> str:
        return self.plain_mode_combo.currentText()

    def set_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.progress_label.setText(message)

    def set_candidates(self, job_id: str, candidates: list[LyricCandidate]) -> None:
        self._candidates[job_id] = candidates
        row = self._row_for_job(job_id)
        if row < 0:
            return
        job = self._jobs[job_id]
        best = _best_batch_candidate(candidates)
        if not best:
            values = ["No match", "-", "-", "No match"]
        else:
            values = [
                best.provider,
                best.kind,
                f"{best.confidence}%",
                _batch_candidate_action(best, bool(job.result)),
            ]
        for column, value in zip((1, 2, 3, 4), values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            self.table.setItem(row, column, item)

    def _row_for_job(self, job_id: str) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == job_id:
                return row
        return -1


def _candidate_label(candidate: LyricCandidate) -> str:
    parts = [candidate.artist, candidate.title]
    label = " - ".join(part for part in parts if part)
    if candidate.album:
        label = f"{label} ({candidate.album})" if label else candidate.album
    return label or candidate.source_id or "Lyrics"


def _best_batch_candidate(candidates: list[LyricCandidate]) -> LyricCandidate | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.confidence + (12 if item.synced else 0), reverse=True)[0]


def _candidate_is_safe_for_batch(candidate: LyricCandidate, has_ai_timing: bool) -> bool:
    if candidate.synced:
        return candidate.confidence >= 82
    return candidate.confidence >= (55 if has_ai_timing else 68)


def _batch_candidate_action(candidate: LyricCandidate, has_ai_timing: bool) -> str:
    if candidate.synced and candidate.confidence >= 82:
        return "Save synced"
    if candidate.synced:
        return "Review"
    if has_ai_timing and candidate.confidence >= 55:
        return "Plain"
    if candidate.confidence >= 68:
        return "Plain"
    return "Review"


def _safe_provider_suffix(provider: str) -> str:
    suffix = "".join(char for char in provider.replace("/", "-") if char.isalnum() or char in {" ", "-", "_"})
    return suffix.strip().replace(" ", "-") or "lyrics"


def _cuda_available() -> bool:
    from app.core.cuda import ctranslate2_cuda_available

    return ctranslate2_cuda_available()


def _setting_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _format_position(position_ms: int) -> str:
    position_ms = max(0, position_ms)
    total_hundredths = position_ms // 10
    minutes, hundredths_remaining = divmod(total_hundredths, 60 * 100)
    seconds, hundredths = divmod(hundredths_remaining, 100)
    return f"{minutes:02d}:{seconds:02d}.{hundredths:02d}"


def _join_optional(left: str | None, right: str | None) -> str | None:
    left_text = (left or "").strip()
    right_text = (right or "").strip()
    joined = " ".join(part for part in (left_text, right_text) if part)
    return joined or None
