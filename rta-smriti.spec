from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files(
    "rta_brain",
    includes=["static/*", "static/assets/*", "data/*.json"],
)

analysis = Analysis(
    ["rta-brain.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "sentence_transformers", "transformers", "torch", "tensorflow",
        "numpy", "scipy", "pandas", "tiktoken", "tree_sitter_language_pack",
    ],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="rta-brain",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
