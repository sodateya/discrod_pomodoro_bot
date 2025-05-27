# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, collect_data_files

nacl_binaries = collect_dynamic_libs('nacl')  # PyNaClのDLL類
nacl_hiddenimports = collect_submodules('nacl')  # naclのサブモジュール全部
nacl_datas = collect_data_files('nacl')

a = Analysis(
    ['bot.py'],
    pathex=[r'C:\Users\takuya\OneDrive\デスクトップ\discrod_pomodoro_bot'],  # 必要なら変更
    binaries=nacl_binaries,
    datas=[
        ('sounds/start.mp3', 'sounds'),
        ('sounds/break.mp3', 'sounds'),
        ('.env', '.'),  # .envはexe横に置く
    ] + nacl_datas,
    hiddenimports=[
        'nacl',
        'nacl.secret',
        'nacl.utils',
        'nacl.public',
        'nacl.signing',
        'nacl.encoding',
        'nacl.hash',
        'nacl.bindings',
        'nacl.exceptions',
        'discord.voice_client',
        'discord.gateway',
        'discord.ext.commands',
        'discord.ext.tasks',
        'discord',
        'discord.ext',
        'cffi',
        'cffi.api',
        'cffi.cparser',
        'cffi.cffi_opcode',
        'cffi.commontypes',
        'cffi.error',
        'cffi.lock',
        'cffi.model',
        'cffi.verifier',
        'cffi.vengine_cpy',
        'cffi.vengine_gen',
        'cffi._cffi_include',
        'cffi._cffi_include._pycparser',
        'cffi._cffi_include._pycparser.ast_transforms',
        'cffi._cffi_include._pycparser.c_ast',
        'cffi._cffi_include._pycparser.c_lexer',
        'cffi._cffi_include._pycparser.c_parser',
        'cffi._cffi_include._pycparser.lextab',
        'cffi._cffi_include._pycparser.parsetab',
        'cffi._cffi_include._pycparser.ply',
        'cffi._cffi_include._pycparser.ply.cpp',
        'cffi._cffi_include._pycparser.ply.ctokens',
        'cffi._cffi_include._pycparser.ply.doctools',
        'cffi._cffi_include._pycparser.ply.lex',
        'cffi._cffi_include._pycparser.ply.yacc',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='bot'
)
