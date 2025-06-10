from collective.ftw.upgrade.tests.layers import COMPONENT_REGISTRY_ISOLATION
from collective.ftw.upgrade.tests.layers import ConsoleScriptLayer
from collective.ftw.upgrade.tests.layers import TEMP_DIRECTORY
from plone.app.testing import IntegrationTesting
from Products.CMFCore.utils import getToolByName
from unittest import TestCase


COMPONENT_REGISTRY_ISOLATION_INTEGRATION = IntegrationTesting(
    bases=(COMPONENT_REGISTRY_ISOLATION, ),
    name="collective.ftw.upgrade:test_component_registry_isolation_layer:integration")


GENERICSETUP_PROFILE_ZCML = '''
<configure
    xmlns="http://namespaces.zope.org/zope"
    xmlns:genericsetup="http://namespaces.zope.org/genericsetup"
    xmlns:i18n="http://namespaces.zope.org/i18n"
    i18n_domain="collective.ftw.upgrade"
    package="collective.ftw.upgrade">

    <genericsetup:registerProfile
        name="default"
        title="collective.ftw.upgrade"
        directory="."
        provides="Products.GenericSetup.interfaces.EXTENSION"
        />

</configure>
'''


class TestComponentRegistryIsolationLayer(TestCase):
    layer = COMPONENT_REGISTRY_ISOLATION_INTEGRATION

    def test_loading_zcml_string(self):
        self.assertFalse(self.profile_exists(),
                         'Component registry is not isolated per test.')
        self.layer['load_zcml_string'](GENERICSETUP_PROFILE_ZCML)
        self.assertTrue(self.profile_exists(),
                        'Failed to register profile.')

    def test_z3c_isolation_works(self):
        # Actually, this should fail here or in "test_loading_zcml_string"
        # because both register the same utility, which should conflict
        # when not teared down properly.
        self.assertFalse(self.profile_exists(),
                         'Component registry is not isolated per test.')
        self.layer['load_zcml_string'](GENERICSETUP_PROFILE_ZCML)
        self.assertTrue(self.profile_exists(),
                        'Failed to register profile.')

    def profile_exists(self):
        portal_setup = getToolByName(self.layer['portal'], 'portal_setup')
        try:
            portal_setup.getProfileInfo('collective.ftw.upgrade:default')
        except KeyError:
            return False
        else:
            return True


CONSOLE_SCRIPT_TESTING = ConsoleScriptLayer('collective.ftw.upgrade')


class TestConsoleScriptLayer(TestCase):
    layer = CONSOLE_SCRIPT_TESTING

    def test_buildout_script_is_generated(self):
        self.assertTrue(self.layer['root_path'].joinpath('bin', 'buildout').is_file(),
                        'bin/buildout script was not generated.')

    def test_buildout_config_is_generated(self):
        self.assertTrue(self.layer['root_path'].joinpath('buildout.cfg').is_file(),
                        'buildout.cfg script was not generated.')

    def test_buildout_directory_is_isolated_for_each_test(self):
        path = self.layer['root_path'].joinpath('the-file.txt')
        self.assertFalse(path.exists(), 'Additionally created files in buildout'
                         ' directory are not removed on test tear down.')
        path.write_text('something')

    test_buildout_directory_is_isolated_for_each_test2 = \
        test_buildout_directory_is_isolated_for_each_test

    def test_python_script_with_environment_is_generated(self):
        code = "from collective.ftw.upgrade.tests import layers; print(layers.__name__)"
        exitcode, output = self.layer['execute_script'](f'py -c "{code}"')
        self.assertEqual('collective.ftw.upgrade.tests.layers', output.splitlines()[0])


class TestTempDirectoryLayer(TestCase):
    layer = TEMP_DIRECTORY

    def test_temp_directory_is_writeable(self):
        file_path = self.layer['temp_directory'].joinpath('file.txt')
        file_path.write_text('something')
        self.assertEqual('something', file_path.read_text())

        dir_path = self.layer['temp_directory'].joinpath('directory')
        dir_path.mkdir()
        self.assertTrue(dir_path.is_dir(), 'Directory was not created.')

    def test_directory_is_cleaned_up_after_every_test(self):
        dir_path = self.layer['temp_directory'].joinpath('the-directory')
        file_path = dir_path.joinpath('the-file.txt')
        self.assertFalse(dir_path.exists(), 'Directory was not cleaned up after test.')
        self.assertFalse(file_path.exists(), 'File was not cleaned up after test.')

        dir_path.mkdir()
        file_path.write_text('something')

    # This makes sure that the test is run twice, so that it would fail when
    # the directory wouldn't be cleaned up properly.
    test_directory_is_cleaned_up_after_every_test2 = \
        test_directory_is_cleaned_up_after_every_test
