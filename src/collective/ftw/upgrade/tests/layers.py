from packaging.requirements import Requirement
from path import Path
from plone.app.testing import PLONE_FIXTURE
from plone.testing import Layer
from plone.testing import zca
from zope.configuration import xmlconfig

import importlib
import logging
import os
import tempfile
import zc.buildout.easy_install
import zc.buildout.testing


class ComponentRegistryIsolationLayer(Layer):
    defaultBases = (PLONE_FIXTURE, )

    def setUp(self):
        self['load_zcml_string'] = self.load_zcml_string

    def testSetUp(self):
        self['configurationContext'] = zca.stackConfigurationContext(
            self.get('configurationContext'),
            name='collective.ftw.upgrade.component_registry_isolation')
        zca.pushGlobalRegistry()

    def testTearDown(self):
        del self['configurationContext']
        zca.popGlobalRegistry()

    def load_zcml_string(self, *zcml_lines):
        zcml = '\n'.join(zcml_lines)
        xmlconfig.string(zcml, context=self['configurationContext'])

    def load_zcml_file(self, filename, module):
        xmlconfig.file(filename, module,
                       context=self['configurationContext'])


COMPONENT_REGISTRY_ISOLATION = ComponentRegistryIsolationLayer()


CONSOLE_SCRIPT_BUILDOUT_TEMPLATE = """[buildout]
parts =
    package

[package]
recipe = zc.recipe.egg:script
eggs = {package_name}{extras}
interpreter = py

[versions]
{versions}
"""


class ConsoleScriptLayer(Layer):

    def __init__(self,
                 package_name,
                 extras=('test',),
                 buildout_template=CONSOLE_SCRIPT_BUILDOUT_TEMPLATE,
                 bases=None,
                 name=None,
                 module=None):

        super().__init__(bases=bases,
                                                 name=name,
                                                 module=module)
        self.package_name = package_name
        self.extras = extras
        self.buildout_template = buildout_template

    def setUp(self):
        zc.buildout.testing.buildoutSetUp(self)
        self['root_path'] = Path(self.sample_buildout)
        self['execute_script'] = self.execute_script
        del self.globs['get']

        dependencies = self.get_dependencies_with_pinnings()
        self.mark_dependencies_for_development(dependencies)
        self.write('buildout.cfg', self.get_buildout_cfg(dependencies))
        self.execute_script('buildout')

        self.filesystem_snapshot = set(Path(self.sample_buildout).walk())

    def tearDown(self):
        zc.buildout.testing.buildoutTearDown(self)
        pypi_url = 'http://pypi.python.org/simple'
        zc.buildout.easy_install.default_index_url = pypi_url
        os.environ['buildout-testing-index-url'] = pypi_url
        zc.buildout.easy_install._indexes = {}
        logging.shutdown()

    def testTearDown(self):
        for path in (set(Path(self.sample_buildout).walk())
                     - self.filesystem_snapshot):
            if path.is_dir():
                path.rmtree()
            if path.is_file():
                path.remove()

    def execute_script(self, command, assert_exitcode=True):
        command = self['root_path'] + '/bin/' + command
        print(command)
        output, exitcode = self.system(
            command, with_exit_code=True).split('EXIT CODE: ')
        exitcode = int(exitcode)

        if assert_exitcode:
            assert exitcode == 0, ('Expected exit code 0, got'
                                   ' {} for "{}".\nOutput:\n{}'.format(
                                       exitcode, command, output))

        return exitcode, output

    def get_buildout_cfg(self, dependencies):
        extras = self.extras and '[{}]'.format(', '.join(self.extras)) or ''
        versions = '\n'.join('='.join((name, version))
                             for (name, version) in dependencies.items())

        return self.buildout_template.format(package_name=self.package_name,
                                             versions=versions,
                                             extras=extras)

    def mark_dependencies_for_development(self, dependencies):
        for pkgname in sorted(dependencies.keys()):
            zc.buildout.testing.install_develop(pkgname, self)

    def get_dependencies_with_pinnings(self):
        dependencies = self.resolve_dependency_versions(self.package_name,
                                                        extras=self.extras)

        assert 'zc-recipe-egg' in dependencies, \
            'For using the ConsoleScriptLayer you need to put "zc.recipe.egg" in' + \
            ' the test dependencies of your package.'

        self.resolve_dependency_versions('zope.untrustedpython', dependencies)
        return dependencies

    def resolve_dependency_versions(self, pkgname, result=None, extras=()):
        result = result or {}
        if pkgname in result or pkgname in ('setuptools', 'zc.buildout'):
            return result

        try:
            dist = importlib.metadata.distribution(pkgname)
        except importlib.metadata.PackageNotFoundError:
            return result

        result[pkgname] = dist.version
        for pkg in dist.requires or []:
            requirement = Requirement(pkg)
            for extra in extras:
                if f"extra == '{extra}'" in pkg:
                    self.resolve_dependency_versions(requirement.name, result)

        return result

    @property
    def globs(self):
        return self.__dict__


class TempDirectoryLayer(Layer):

    def testSetUp(self):
        self['temp_directory'] = Path(tempfile.mkdtemp('collective.ftw.upgrade'))

    def testTearDown(self):
        self['temp_directory'].rmtree_p()


TEMP_DIRECTORY = TempDirectoryLayer()
