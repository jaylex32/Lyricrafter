from app.core.performance import cpu_threads_for_mode


def test_cpu_performance_modes_scale_to_available_threads() -> None:
    assert cpu_threads_for_mode("background", logical_threads=20) == 5
    assert cpu_threads_for_mode("balanced", logical_threads=20) == 8
    assert cpu_threads_for_mode("auto", logical_threads=20) == 12
    assert cpu_threads_for_mode("maximum", logical_threads=20) == 20


def test_cpu_performance_custom_value_is_clamped() -> None:
    assert cpu_threads_for_mode("custom", 14, logical_threads=20) == 14
    assert cpu_threads_for_mode("custom", 99, logical_threads=20) == 20
    assert cpu_threads_for_mode("custom", 0, logical_threads=20) == 1


def test_unknown_cpu_performance_mode_uses_auto() -> None:
    assert cpu_threads_for_mode("invalid", logical_threads=8) == 5
