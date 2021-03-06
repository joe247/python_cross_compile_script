{
	'repo_type' : 'git',
	'url' : 'https://chromium.googlesource.com/angle/angle',
	'patches' : (
		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/0002-Cross-compile-hacks.patch'                             ,'-p1'),
		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/0003-rename-sprintf_s.patch'                                ,'-p1'),
		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/0004-string_utils-cpp.patch'                                ,'-p1'),
		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/angle-0002-install-fixed.patch'                             ,'-p1'),
		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/angle-0003-add-option-for-targeting-cpu-architecture.patch' ,'-p1'),
	),
	'needs_make':False,
	'needs_make_install':False,
	'needs_configure':False,
	'run_post_patch': (
		'if [ ! -f "already_done" ] ; then sed -i 's/'python'/'python2'/' gyp/warnings.gyp ; fi',
		'if [ ! -f "already_done" ] ; then make uninstall PREFIX={target_prefix} ; fi',
		'if [ ! -f "already_done" ] ; then make uninstall PREFIX={target_prefix} ; fi',
		'if [ ! -f "already_done" ] ; then cmake -E remove_directory build ; fi',
		'if [ ! -f "already_done" ] ; then gyp -Duse_ozone=0 -DOS=win -Dangle_gl_library_type=static_library -Dangle_use_commit_id=1 --depth . -I gyp/common.gypi src/angle.gyp --no-parallel --format=make --generator-output=build -Dangle_enable_vulkan=0 -Dtarget_cpu=x64 ; fi',
		'if [ ! -f "already_done" ] ; then make -C build/ commit_id ; fi',
		'if [ ! -f "already_done" ] ; then cmake -E copy build/out/Debug/obj/gen/angle/id/commit.h src/id/commit.h ; fi',
		'if [ ! -f "already_done" ] ; then make -C build {make_prefix_options} BUILDTYPE=Debug {make_cpu_count} ; fi',
		'if [ ! -f "already_done" ] ; then chmod u+x ./move-libs.sh && ./move-libs.sh {bit_name}-w64-mingw32 Debug ; fi',
		'if [ ! -f "already_done" ] ; then make install PREFIX={target_prefix} ; fi',
		'if [ ! -f "already_done" ] ; then touch already_done ; fi',
	),
	'packages': {
		'arch' : [ 'gyp' ],
	},
	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ANGLE' },
}