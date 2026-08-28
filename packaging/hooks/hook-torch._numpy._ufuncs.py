# Torch builds this module's public functions through module-level loops.
# Collect source only so PyInstaller does not optimize away loop variables.
module_collection_mode = "py"
