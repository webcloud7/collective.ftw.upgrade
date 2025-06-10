from collective.ftw.upgrade.tests.base import JsonApiTestCase
from collective.ftw.upgrade.utils import get_portal_migration
from datetime import datetime
from ftw.builder import Builder
from Products.CMFPlone.factory import _DEFAULT_PROFILE

import re
import transaction


class TestPloneSiteJsonApi(JsonApiTestCase):

    def test_api_discovery(self):
        response = self.api_request('GET', '')

        self.assert_json_equal(
            {'api_version': 'v1',
             'actions':
                 [{'description': ('Executes a list of profiles, each '
                                   'identified by their ID.'),
                   'name': 'execute_profiles',
                   'request_method': 'POST',
                   'required_params': ['profiles:list']},

                  {'name': 'execute_proposed_upgrades',
                   'required_params': [],
                   'description': 'Executes all proposed upgrades.',
                   'request_method': 'POST'},

                  {'name': 'execute_upgrades',
                   'required_params': ['upgrades:list'],
                   'description': 'Executes a list of upgrades, each identified by'
                   ' the upgrade ID in the form "[dest-version]@[profile ID]".',
                   'request_method': 'POST'},

                  {'name': 'get_profile',
                   'required_params': ['profileid'],
                   'description': 'Returns the profile with the id "profileid" as hash.',
                   'request_method': 'GET'},

                  {'name': 'list_profiles',
                   'required_params': [],
                   'description': 'Returns a list of all installed profiles.',
                   'request_method': 'GET'},

                  {'name': 'list_profiles_proposing_upgrades',
                   'required_params': [],
                   'description': 'Returns a list of profiles with proposed upgrade steps.'
                   ' The upgrade steps of each profile only include proposed upgrades.',
                   'request_method': 'GET'},

                  {'name': 'list_proposed_upgrades',
                   'required_params': [],
                   'description': 'Returns a list of proposed upgrades.',
                   'request_method': 'GET'},

                  {'name': 'plone_upgrade',
                   'required_params': [],
                   'description': 'Upgrade the Plone Site. This is what you would manually do in the @@plone-upgrade view.',
                   'request_method': 'POST'},

                  {'name': 'plone_upgrade_needed',
                   'required_params': [],
                   'description': 'Returns "true" when Plone needs to be upgraded.',
                   'request_method': 'GET'}]},

            response.json())

    def test_get_profile(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('plone upgrade step').upgrading('1', to='2'))
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            self.clear_recorded_upgrades('the.package:default')

            response = self.api_request('GET', 'get_profile', dict(profileid='the.package:default'))
            self.assertEqual('application/json; charset=utf-8',
                             response.headers.get('content-type'))

            self.assert_json_equal(
                {'id': 'the.package:default',
                 'title': 'the.package',
                 'product': 'the.package',
                 'db_version': '1',
                 'fs_version': '20110101000000',
                 'outdated_fs_version': False,
                 'upgrades': [

                        {'id': '2@the.package:default',
                         'title': '',
                         'source': '1',
                         'dest': '2',
                         'proposed': True,
                         'deferrable': False,
                         'done': False,
                         'orphan': False,
                         'outdated_fs_version': False},

                        {'id': '20110101000000@the.package:default',
                         'title': 'Upgrade.',
                         'source': '2',
                         'dest': '20110101000000',
                         'proposed': True,
                         'deferrable': False,
                         'done': False,
                         'orphan': False,
                         'outdated_fs_version': False},
                        ]},

                response.json())

    def test_get_profile_requires_profileid(self):
        with self.expect_api_error(status=400,
                                   message='Param missing',
                                   details='The param "profileid" is required'
                                   ' for this API action.') as result:
            result['response'] = self.api_request('GET', 'get_profile')

    def test_get_profile_requires_GET(self):
        with self.expect_api_error(status=405,
                                   message='Method Not Allowed',
                                   details='Action requires GET') as result:
            result['response'] = self.api_request('POST', 'get_profile', {'profileid': 'the.package:default'})
        self.assertEqual('GET', result['response'].headers.get('allow'))

    def test_get_unkown_profile_returns_error(self):
        with self.expect_api_error(status=400,
                                   message='Profile not available',
                                   details='The profile "something:default" is wrong'
                                   ' or not installed on this Plone site.') as result:
            result['response'] = self.api_request('GET', 'get_profile', {'profileid': 'something:default'})

    def test_cyclic_dependency_errors_are_handled(self):
        self.package.with_profile(Builder('genericsetup profile')
                                  .named('foo')
                                  .with_upgrade(self.default_upgrade())
                                  .with_dependencies('the.package:bar'))

        self.package.with_profile(Builder('genericsetup profile')
                                  .named('bar')
                                  .with_upgrade(self.default_upgrade())
                                  .with_dependencies('the.package:foo'))

        with self.package_created():
            self.install_profile('the.package:foo')
            self.install_profile('the.package:bar')

            with self.expect_api_error(status=500,
                                       message='Cyclic dependencies',
                                       details='There are cyclic Generic Setup profile'
                                       ' dependencies.') as result:
                result['response'] = self.api_request('GET', 'get_profile', {'profileid': 'the.package:foo'})

    def test_list_profiles(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))))
        self.package.with_profile(
            Builder('genericsetup profile')
            .named('foo')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))))

        with self.package_created():
            self.install_profile('the.package:default')
            self.install_profile('the.package:foo')

            response = self.api_request('GET', 'list_profiles')
            self.assertEqual('application/json; charset=utf-8',
                             response.headers.get('content-type'))

            self.assert_json_contains_profile(
                {'id': 'the.package:default',
                 'title': 'the.package',
                 'product': 'the.package',
                 'db_version': '20110101000000',
                 'fs_version': '20110101000000',
                 'outdated_fs_version': False,
                 'upgrades': [
                        {'id': '20110101000000@the.package:default',
                         'title': 'Upgrade.',
                         'source': '10000000000000',
                         'dest': '20110101000000',
                         'proposed': False,
                         'deferrable': False,
                         'done': True,
                         'orphan': False,
                         'outdated_fs_version': False},
                        ]},
                response.json())

            self.assert_json_contains_profile(
                {'id': 'the.package:foo',
                 'title': 'the.package',
                 'product': 'the.package',
                 'db_version': '20110101000000',
                 'fs_version': '20110101000000',
                 'outdated_fs_version': False,
                 'upgrades': [
                        {'id': '20110101000000@the.package:foo',
                         'title': 'Upgrade.',
                         'source': '10000000000000',
                         'dest': '20110101000000',
                         'proposed': False,
                         'deferrable': False,
                         'done': True,
                         'orphan': False,
                         'outdated_fs_version': False},
                        ]},
                response.json())

    def test_list_profiles_requires_authentication(self):
        with self.expect_api_error(status=401,
                                   message='Unauthorized',
                                   details='Admin authorization required.') as result:
            result['response'] = self.api_request('GET', 'list_profiles', authenticate=False)

    def test_list_profiles_proposing_upgrades(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('plone upgrade step').upgrading('1', to='2'))
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))))

        with self.package_created():
            self.install_profile('the.package:default', version='2')
            self.clear_recorded_upgrades('the.package:default')

            response = self.api_request('GET', 'list_profiles_proposing_upgrades')
            self.assertEqual('application/json; charset=utf-8',
                             response.headers.get('content-type'))

            self.assert_json_contains_profile(
                {'id': 'the.package:default',
                 'title': 'the.package',
                 'product': 'the.package',
                 'db_version': '2',
                 'fs_version': '20110101000000',
                 'outdated_fs_version': False,
                 'upgrades': [
                        {'id': '20110101000000@the.package:default',
                         'title': 'Upgrade.',
                         'source': '2',
                         'dest': '20110101000000',
                         'proposed': True,
                         'deferrable': False,
                         'done': False,
                         'orphan': False,
                         'outdated_fs_version': False},
                        ]},
                response.json())

    def test_list_proposed_upgrades_when_empty(self):
        response = self.api_request('GET', 'list_proposed_upgrades')
        self.assertEqual('application/json; charset=utf-8',
                         response.headers.get('content-type'))

    def test_list_proposed_upgrades(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('plone upgrade step').upgrading('1', to='2')))

        self.package.with_profile(
            Builder('genericsetup profile')
            .named('foo')
            .with_upgrade(Builder('plone upgrade step').upgrading('2', to='3')))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            self.install_profile('the.package:foo', version='1')

            response = self.api_request('GET', 'list_proposed_upgrades')
            self.assertEqual('application/json; charset=utf-8',
                             response.headers.get('content-type'))

            self.assert_json_contains(
                {'id': '2@the.package:default',
                 'title': '',
                 'source': '1',
                 'dest': '2',
                 'proposed': True,
                 'deferrable': False,
                 'done': False,
                 'orphan': False,
                 'outdated_fs_version': False},
                response.json())

            self.assert_json_contains(
                {'id': '3@the.package:foo',
                 'title': '',
                 'source': '2',
                 'dest': '3',
                 'proposed': True,
                 'deferrable': False,
                 'done': False,
                 'orphan': False,
                 'outdated_fs_version': False},
                response.json())

    def test_execute_upgrades_installs_upgrades_in_gatherer_order(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The first upgrade step'))
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2012, 2, 2))
                          .named('The second upgrade step')))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            self.clear_recorded_upgrades('the.package:default')
            self.assertFalse(self.is_installed('the.package:default', datetime(2011, 1, 1)))
            self.assertFalse(self.is_installed('the.package:default', datetime(2012, 2, 2)))

            response = self.api_request('POST', 'execute_upgrades', (
                    ('upgrades:list', '20120202000000@the.package:default'),
                    ('upgrades:list', '20110101000000@the.package:default')))

            transaction.begin()
            self.assertTrue(self.is_installed('the.package:default', datetime(2011, 1, 1)))
            self.assertTrue(self.is_installed('the.package:default', datetime(2012, 2, 2)))
            self.assertEqual(
                ['UPGRADE STEP the.package:default: The first upgrade step.',
                 'UPGRADE STEP the.package:default: The second upgrade step.'],
                re.findall(r'UPGRADE STEP.*', response.text))

            self.assertIn('Result: SUCCESS', response.text)

    def test_execute_upgrades_requires_upgrades_param(self):
        with self.expect_api_error(status=400,
                                   message='Param missing',
                                   details='The param "upgrades:list" is required for'
                                   ' this API action.') as result:
            result['response'] = self.api_request('POST', 'execute_upgrades')

    def test_execute_upgrades_validates_upgrade_ids(self):
        with self.expect_api_error(status=400,
                                   message='Upgrade not found',
                                   details='The upgrade "foo@bar:default" is unkown.') as result:
            result['response'] = self.api_request('POST', 'execute_upgrades', {'upgrades:list': 'foo@bar:default'})

    def test_execute_upgrades_requires_POST(self):
        with self.expect_api_error(status=405,
                                   message='Method Not Allowed',
                                   details='Action requires POST') as result:
            result['response'] = self.api_request('GET', 'execute_upgrades', {'upgrades:list': 'foo@bar:default'})
        self.assertEqual('POST', result['response'].headers.get('allow'))

    def test_execute_upgrades_not_allowed_when_plone_outdated(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The first upgrade step')))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            self.clear_recorded_upgrades('the.package:default')
            portal_migration = get_portal_migration(self.layer['portal'])
            portal_migration.setInstanceVersion('1.0.0')
            transaction.commit()
            self.assertFalse(self.is_installed('the.package:default', datetime(2011, 1, 1)))

            with self.expect_api_error(
                    status=400,
                    message='Plone site outdated',
                    details='The Plone site is outdated and needs to'
                    ' be upgraded first using the regular Plone'
                    ' upgrading tools.') as result:
                result['response'] = self.api_request(
                    'POST',
                    'execute_upgrades',
                    {'upgrades:list': '20110101000000@the.package:default'})
            self.assertFalse(self.is_installed('the.package:default', datetime(2011, 1, 1)))

    def test_execute_upgrades_explicitly_allowed_even_on_outdated_plone(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The first upgrade step')))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            self.clear_recorded_upgrades('the.package:default')
            portal_migration = get_portal_migration(self.layer['portal'])
            portal_migration.setInstanceVersion('1.0.0')
            transaction.commit()
            self.assertFalse(self.is_installed('the.package:default', datetime(2011, 1, 1)))

            response = self.api_request(
                'POST',
                'execute_upgrades',
                {'upgrades:list': '20110101000000@the.package:default',
                 'allow_outdated': True})

            transaction.begin()
            self.assertTrue(self.is_installed('the.package:default', datetime(2011, 1, 1)))
            self.assertEqual(
                ['UPGRADE STEP the.package:default: The first upgrade step.'],
                re.findall(r'UPGRADE STEP.*', response.text))
            self.assertIn('Result: SUCCESS', response.text)

    def test_execute_proposed_upgrades(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The upgrade')))

        with self.package_created():
            self.install_profile('the.package:default', version='2')
            self.clear_recorded_upgrades('the.package:default')

            self.assertFalse(self.is_installed('the.package:default', datetime(2011, 1, 1)))
            response = self.api_request('POST', 'execute_proposed_upgrades')
            transaction.begin()
            self.assertTrue(self.is_installed('the.package:default', datetime(2011, 1, 1)))

            self.assertIn('UPGRADE STEP the.package:default: The upgrade.',
                          response.text)
            self.assertIn('Result: SUCCESS', response.text)

    def test_execute_proposed_upgrades_for_profile(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The upgrade')))

        self.package.with_profile(
            Builder('genericsetup profile')
            .named('foo')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))))

        with self.package_created():
            self.install_profile('the.package:default', version='2')
            self.clear_recorded_upgrades('the.package:default')
            self.install_profile('the.package:foo', version='2')
            self.clear_recorded_upgrades('the.package:foo')

            self.assertFalse(self.is_installed('the.package:default', datetime(2011, 1, 1)))
            self.assertFalse(self.is_installed('the.package:foo', datetime(2011, 1, 1)))
            response = self.api_request('POST', 'execute_proposed_upgrades',
                                        {'profiles:list': ['the.package:default']})
            transaction.begin()
            self.assertTrue(self.is_installed('the.package:default', datetime(2011, 1, 1)))
            self.assertFalse(self.is_installed('the.package:foo', datetime(2011, 1, 1)))

            self.assertIn('UPGRADE STEP the.package:default: The upgrade.',
                          response.text)
            self.assertIn('Result: SUCCESS', response.text)

    def test_executing_upgrades_with_failure_results_in_error_result(self):
        def failing_upgrade(setup_context):
            raise KeyError('foo')

        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('plone upgrade step')
                          .upgrading('1', to='2')
                          .calling(failing_upgrade)))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            response = self.api_request('POST', 'execute_proposed_upgrades')
            self.assertIn('Result: FAILURE', response.text)

    def test_execute_profiles_standard(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The upgrade')))

        with self.package_created():
            response = self.api_request('POST', 'execute_profiles',
                                        {'profiles:list': ['the.package:default']})

            transaction.begin()
            self.assertEqual(self.portal_setup.getLastVersionForProfile(
                'the.package:default'), ('20110101000000', ))
            self.assertTrue(self.is_installed(
                'the.package:default', datetime(2011, 1, 1)))
            self.assertIn('Done installing profile the.package:default.',
                          response.text)
            self.assertIn('Result: SUCCESS', response.text)

    def test_execute_profiles_already_installed(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The upgrade')))

        with self.package_created():
            self.portal_setup.runAllImportStepsFromProfile(
                'profile-the.package:default')
            transaction.commit()
            response = self.api_request('POST', 'execute_profiles',
                                        {'profiles:list': ['the.package:default']})
            self.assertIn(
                'Ignoring already installed profile the.package:default.',
                response.text)
            self.assertIn('Result: SUCCESS', response.text)

    def test_execute_profiles_force_when_already_installed(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step').to(datetime(2011, 1, 1))
                          .named('The upgrade')))

        with self.package_created():
            self.portal_setup.runAllImportStepsFromProfile(
                'profile-the.package:default')
            transaction.commit()
            response = self.api_request('POST', 'execute_profiles',
                                        {'profiles:list': ['the.package:default'],
                                         'force_reinstall': True})
            self.assertNotIn(
                'Ignoring already installed profile the.package:default.',
                response.text)
            self.assertIn('Done installing profile the.package:default.',
                          response.text)
            self.assertIn('Result: SUCCESS', response.text)

    def test_execute_profiles_not_found(self):
        with self.expect_api_error(
                status=400,
                message='Profile not found',
                details='The profile "the.package:default" is unknown.') as result:
            result['response'] = self.api_request(
                'POST', 'execute_profiles', {'profiles:list': ['the.package:default']})

    def test_plone_upgrade_needed(self):
        response = self.api_request('GET', 'plone_upgrade_needed')
        self.assertEqual(False, response.json())

        self.portal_setup.setLastVersionForProfile(_DEFAULT_PROFILE, '4')
        transaction.commit()
        response = self.api_request('GET', 'plone_upgrade_needed')
        self.assertEqual(True, response.json())
