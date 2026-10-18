project('native-meson-receiver-control', ['c', 'cpp'],
  default_options: ['default_library=static', 'cpp_std=c++20'])
python = import('python').find_installation()
run_command(python, files('tool-observer.py'),
  join_paths(meson.current_build_dir(), 'reached-tools.json'), check: true)
graphite = dependency('graphite2', method: 'pkg-config', static: true, required: true)
icu = dependency('icu-uc', method: 'pkg-config', static: true, required: true)
parts = static_library('receiver-parts', ['probe.c', 'probe.cpp'], install: false)
probe = executable('receiver-probe', 'main.cpp', link_with: parts,
  dependencies: [graphite, icu], install: false)
alias_target('libs', parts, probe)
