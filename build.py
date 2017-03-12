# Copyright 2017 Virgil Dupras
#
# This software is licensed under the "GPLv3" License as described in the "LICENSE" file,
# which should be included with this package. The terms are also available at
# http://www.gnu.org/licenses/gpl-3.0.html

import sys
sys.path.append('dupeguru')
import os
import os.path as op
from optparse import OptionParser
import shutil
import compileall

from setuptools import setup, Extension

from hscommon import sphinxgen
from hscommon.build import (
    add_to_pythonpath, print_and_do, copy_packages, filereplace,
    get_module_version, move_all, copy_all, OSXAppStructure,
    build_cocoalib_xibless, fix_qt_resource_file, build_cocoa_ext, copy_embeddable_python_dylib,
    collect_stdlib_dependencies
)
from hscommon import loc
from hscommon.plat import ISOSX
from hscommon.util import ensure_folder, delete_files_with_pattern

def parse_args():
    usage = "usage: %prog [options]"
    parser = OptionParser(usage=usage)
    parser.add_option(
        '--clean', action='store_true', dest='clean',
        help="Clean build folder before building"
    )
    parser.add_option(
        '--doc', action='store_true', dest='doc',
        help="Build only the help file"
    )
    parser.add_option(
        '--dev', action='store_true', dest='dev', default=False,
        help="If this flag is set, will configure for dev builds."
    )
    parser.add_option(
        '--loc', action='store_true', dest='loc',
        help="Build only localization"
    )
    parser.add_option(
        '--cocoa-ext', action='store_true', dest='cocoa_ext',
        help="Build only Cocoa extensions"
    )
    parser.add_option(
        '--cocoa-compile', action='store_true', dest='cocoa_compile',
        help="Build only Cocoa executable"
    )
    parser.add_option(
        '--xibless', action='store_true', dest='xibless',
        help="Build only xibless UIs"
    )
    parser.add_option(
        '--updatepot', action='store_true', dest='updatepot',
        help="Generate .pot files from source code."
    )
    parser.add_option(
        '--mergepot', action='store_true', dest='mergepot',
        help="Update all .po files based on .pot files."
    )
    parser.add_option(
        '--normpo', action='store_true', dest='normpo',
        help="Normalize all PO files (do this before commit)."
    )
    (options, args) = parser.parse_args()
    return options

def cocoa_app():
    app_path = 'build/dupeGuru.app'
    return OSXAppStructure(app_path)

def build_xibless(dest='cocoa/autogen'):
    import xibless
    ensure_folder(dest)
    FNPAIRS = [
        ('ignore_list_dialog.py', 'IgnoreListDialog_UI'),
        ('deletion_options.py', 'DeletionOptions_UI'),
        ('problem_dialog.py', 'ProblemDialog_UI'),
        ('directory_panel.py', 'DirectoryPanel_UI'),
        ('prioritize_dialog.py', 'PrioritizeDialog_UI'),
        ('result_window.py', 'ResultWindow_UI'),
        ('main_menu.py', 'MainMenu_UI'),
        ('details_panel.py', 'DetailsPanel_UI'),
        ('details_panel_picture.py', 'DetailsPanelPicture_UI'),
    ]
    for srcname, dstname in FNPAIRS:
        xibless.generate(
            op.join('cocoa', 'ui', srcname), op.join(dest, dstname),
            localizationTable='Localizable'
        )
    for appmode in ('standard', 'music', 'picture'):
        xibless.generate(
            op.join('cocoa', 'ui', 'preferences_panel.py'),
            op.join(dest, 'PreferencesPanel%s_UI' % appmode.capitalize()),
            localizationTable='Localizable',
            args={'appmode': appmode},
        )

def build_cocoa(dev):
    print("Creating OS X app structure")
    app = cocoa_app()
    app_version = get_module_version('core')
    cocoa_project_path = 'cocoa'
    filereplace(op.join(cocoa_project_path, 'InfoTemplate.plist'), op.join('build', 'Info.plist'), version=app_version)
    app.create(op.join('build', 'Info.plist'))
    print("Building localizations")
    build_localizations()
    print("Building xibless UIs")
    build_cocoalib_xibless()
    build_xibless()
    print("Building Python extensions")
    build_cocoa_proxy_module()
    build_cocoa_bridging_interfaces()
    print("Building the cocoa layer")
    copy_embeddable_python_dylib('build')
    pydep_folder = op.join(app.resources, 'py')
    if not op.exists(pydep_folder):
        os.mkdir(pydep_folder)
    shutil.copy(op.join(cocoa_project_path, 'dg_cocoa.py'), 'build')
    tocopy = [
        'dupeguru/core', 'hscommon', 'cocoa/inter', 'cocoalib/cocoa', 'objp', 'send2trash', 'hsaudiotag',
    ]
    copy_packages(tocopy, pydep_folder, create_links=dev)
    sys.path.insert(0, 'build')
    # ModuleFinder can't seem to correctly detect the multiprocessing dependency, so we have
    # to manually specify it.
    extra_deps = ['multiprocessing']
    collect_stdlib_dependencies('build/dg_cocoa.py', pydep_folder, extra_deps=extra_deps)
    del sys.path[0]
    # Views are not referenced by python code, so they're not found by the collector.
    copy_all('build/inter/*.so', op.join(pydep_folder, 'inter'))
    if not dev:
        # Important: Don't ever run delete_files_with_pattern('*.py') on dev builds because you'll
        # be deleting all py files in symlinked folders.
        compileall.compile_dir(pydep_folder, force=True, legacy=True)
        delete_files_with_pattern(pydep_folder, '*.py')
        delete_files_with_pattern(pydep_folder, '__pycache__')
    print("Compiling with WAF")
    os.chdir('cocoa')
    print_and_do('{0} waf configure && {0} waf'.format(sys.executable))
    os.chdir('..')
    app.copy_executable('cocoa/build/dupeGuru')
    build_help()
    print("Copying resources and frameworks")
    image_path = 'cocoa/dupeguru.icns'
    resources = [image_path, 'cocoa/dsa_pub.pem', 'build/dg_cocoa.py', 'build/help']
    app.copy_resources(*resources, use_symlinks=dev)
    app.copy_frameworks('build/Python')
    print("Creating the run.py file")
    tmpl = open('cocoa/run_template.py', 'rt').read()
    run_contents = tmpl.replace('{{app_path}}', app.dest)
    open('run.py', 'wt').write(run_contents)

def build_help():
    print("Generating Help")
    current_path = op.abspath('dupeguru')
    help_basepath = op.join(current_path, 'help', 'en')
    help_destpath = op.join(current_path, '..', 'build', 'help')
    changelog_path = op.join(current_path, 'help', 'changelog')
    tixurl = "https://github.com/hsoft/dupeguru/issues/{}"
    confrepl = {'language': 'en'}
    changelogtmpl = op.join(current_path, 'help', 'changelog.tmpl')
    conftmpl = op.join(current_path, 'help', 'conf.tmpl')
    sphinxgen.gen(help_basepath, help_destpath, changelog_path, tixurl, confrepl, conftmpl, changelogtmpl)

def build_localizations():
    if not op.exists('locale'):
        os.symlink('dupeguru/locale', 'locale')
    loc.compile_all_po('locale')
    app = cocoa_app()
    loc.build_cocoa_localizations(app, en_stringsfile=op.join('cocoa', 'en.lproj', 'Localizable.strings'))
    locale_dest = op.join(app.resources, 'locale')
    if op.exists(locale_dest):
        shutil.rmtree(locale_dest)
    shutil.copytree('locale', locale_dest, ignore=shutil.ignore_patterns('*.po', '*.pot'))

def build_updatepot():
    print("Updating Cocoa strings file.")
    build_cocoalib_xibless('cocoalib/autogen')
    loc.generate_cocoa_strings_from_code('cocoalib', 'cocoalib/en.lproj')
    build_xibless()
    loc.generate_cocoa_strings_from_code('cocoa', 'cocoa/en.lproj')

def build_mergepot():
    print("Updating .po files using .pot files")
    loc.merge_pots_into_pos(op.join('cocoalib', 'locale'))

def build_normpo():
    loc.normalize_all_pos(op.join('cocoalib', 'locale'))

def build_cocoa_proxy_module():
    print("Building Cocoa Proxy")
    import objp.p2o
    objp.p2o.generate_python_proxy_code('cocoalib/cocoa/CocoaProxy.h', 'build/CocoaProxy.m')
    build_cocoa_ext(
        "CocoaProxy", 'cocoalib/cocoa',
        [
            'cocoalib/cocoa/CocoaProxy.m', 'build/CocoaProxy.m', 'build/ObjP.m',
            'cocoalib/HSErrorReportWindow.m', 'cocoa/autogen/HSErrorReportWindow_UI.m'
        ],
        ['AppKit', 'CoreServices'],
        ['cocoalib', 'cocoa/autogen']
    )

def build_cocoa_bridging_interfaces():
    print("Building Cocoa Bridging Interfaces")
    import objp.o2p
    import objp.p2o
    add_to_pythonpath('cocoa')
    add_to_pythonpath('cocoalib')
    from cocoa.inter import (
        PyGUIObject, GUIObjectView, PyColumns, ColumnsView, PyOutline,
        OutlineView, PySelectableList, SelectableListView, PyTable, TableView, PyBaseApp,
        PyTextField, ProgressWindowView, PyProgressWindow
    )
    from inter.deletion_options import PyDeletionOptions, DeletionOptionsView
    from inter.details_panel import PyDetailsPanel, DetailsPanelView
    from inter.directory_outline import PyDirectoryOutline, DirectoryOutlineView
    from inter.prioritize_dialog import PyPrioritizeDialog, PrioritizeDialogView
    from inter.prioritize_list import PyPrioritizeList, PrioritizeListView
    from inter.problem_dialog import PyProblemDialog
    from inter.ignore_list_dialog import PyIgnoreListDialog, IgnoreListDialogView
    from inter.result_table import PyResultTable, ResultTableView
    from inter.stats_label import PyStatsLabel, StatsLabelView
    from inter.app import PyDupeGuru, DupeGuruView
    allclasses = [
        PyGUIObject, PyColumns, PyOutline, PySelectableList, PyTable, PyBaseApp,
        PyDetailsPanel, PyDirectoryOutline, PyPrioritizeDialog, PyPrioritizeList, PyProblemDialog,
        PyIgnoreListDialog, PyDeletionOptions, PyResultTable, PyStatsLabel, PyDupeGuru,
        PyTextField, PyProgressWindow
    ]
    for class_ in allclasses:
        objp.o2p.generate_objc_code(class_, 'cocoa/autogen', inherit=True)
    allclasses = [
        GUIObjectView, ColumnsView, OutlineView, SelectableListView, TableView,
        DetailsPanelView, DirectoryOutlineView, PrioritizeDialogView, PrioritizeListView,
        IgnoreListDialogView, DeletionOptionsView, ResultTableView, StatsLabelView,
        ProgressWindowView, DupeGuruView
    ]
    clsspecs = [objp.o2p.spec_from_python_class(class_) for class_ in allclasses]
    objp.p2o.generate_python_proxy_code_from_clsspec(clsspecs, 'build/CocoaViews.m')
    build_cocoa_ext('CocoaViews', 'cocoa/inter', ['build/CocoaViews.m', 'build/ObjP.m'])

def build_pe_modules():
    print("Building PE Modules")
    exts = [
        Extension(
            "_block",
            [op.join('dupeguru', 'core', 'pe', 'modules', 'block.c'), op.join('dupeguru', 'core', 'pe', 'modules', 'common.c')]
        ),
        Extension(
            "_cache",
            [op.join('dupeguru', 'core', 'pe', 'modules', 'cache.c'), op.join('dupeguru', 'core', 'pe', 'modules', 'common.c')]
        ),
    ]
    exts.append(Extension(
        "_block_osx",
        [op.join('dupeguru', 'core', 'pe', 'modules', 'block_osx.m'), op.join('dupeguru', 'core', 'pe', 'modules', 'common.c')],
        extra_link_args=[
            "-framework", "CoreFoundation",
            "-framework", "Foundation",
            "-framework", "ApplicationServices",
        ]
    ))
    setup(
        script_args=['build_ext', '--inplace'],
        ext_modules=exts,
    )
    move_all('_block*', op.join('dupeguru', 'core', 'pe'))
    move_all('_cache*', op.join('dupeguru', 'core', 'pe'))

def build_normal(dev):
    print("Building dupeGuru with UI cocoa")
    add_to_pythonpath('.')
    build_pe_modules()
    build_cocoa(dev)

def main():
    options = parse_args()
    if options.dev:
        print("Building in Dev mode")
    if options.clean:
        for path in ['build', op.join('cocoa', 'build'), op.join('cocoa', 'autogen')]:
            if op.exists(path):
                shutil.rmtree(path)
    if not op.exists('build'):
        os.mkdir('build')
    if options.doc:
        build_help()
    elif options.loc:
        build_localizations()
    elif options.updatepot:
        build_updatepot()
    elif options.mergepot:
        build_mergepot()
    elif options.normpo:
        build_normpo()
    elif options.cocoa_ext:
        build_cocoa_proxy_module()
        build_cocoa_bridging_interfaces()
    elif options.cocoa_compile:
        os.chdir('cocoa')
        print_and_do('{0} waf configure && {0} waf'.format(sys.executable))
        os.chdir('..')
        cocoa_app().copy_executable('cocoa/build/dupeGuru')
    elif options.xibless:
        build_cocoalib_xibless()
        build_xibless()
    else:
        build_normal(options.dev)

if __name__ == '__main__':
    main()
