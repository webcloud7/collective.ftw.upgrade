from AccessControl import getSecurityManager
from AccessControl.SecurityManagement import setSecurityManager
from bs4 import BeautifulSoup
from collective.ftw.upgrade.directory import scaffold
from collective.ftw.upgrade.indexing import processQueue
from collective.ftw.upgrade.interfaces import IExecutioner
from collective.ftw.upgrade.interfaces import IUpgradeInformationGatherer
from collective.ftw.upgrade.interfaces import IUpgradeStepRecorder
from collective.ftw.upgrade.testing import COMMAND_AND_UPGRADE_FUNCTIONAL_TESTING
from collective.ftw.upgrade.testing import COMMAND_LAYER
from collective.ftw.upgrade.testing import UPGRADE_FUNCTIONAL_TESTING
from collective.ftw.upgrade.tests.helpers import truncate_memory_and_duration
from contextlib import contextmanager
from DateTime import DateTime
from ftw.builder import Builder
from ftw.builder import create
from io import StringIO
from operator import itemgetter
from path import Path
from plone.app.testing import login
from plone.app.testing import setRoles
from plone.app.testing import SITE_OWNER_NAME
from plone.app.testing import SITE_OWNER_PASSWORD
from plone.app.testing import TEST_USER_ID
from plone.app.testing import TEST_USER_PASSWORD
from plone.restapi.testing import RelativeSession
from Products.CMFCore.utils import getToolByName
from unittest import TestCase
from zope.component import getMultiAdapter
from zope.component import queryAdapter

import json
import logging
import lxml.html
import operator
import os
import re
import six
import six.moves.urllib.error
import six.moves.urllib.parse
import six.moves.urllib.request
import transaction


class AssertMixin:
    def assertDictContainsSubset(self, actual, expected, msg=None):
        for key, value in actual.items():
            self.assertEqual(expected.get(key), value, msg)


class UpgradeTestCase(TestCase, AssertMixin):
    layer = UPGRADE_FUNCTIONAL_TESTING

    def setUp(self):
        self.package = (Builder('python package')
                        .at_path(self.directory)
                        .named('the.package'))
        self.portal = self.layer['portal']
        self.portal_setup = getToolByName(self.portal, 'portal_setup')

    def tearDown(self):
        self.teardown_logging()

    def grant(self, *roles):
        setRoles(self.portal, TEST_USER_ID, list(roles))
        transaction.commit()

    def login(self, user, browser=None):
        if hasattr(user, 'getUserName'):
            userid = user.getUserName()
        else:
            userid = user

        security_manager = getSecurityManager()
        if userid == SITE_OWNER_NAME:
            login(self.layer['app'], userid)
        else:
            login(self.portal, userid)

        if browser is not None:
            browser_auth_headers = [
                item for item in browser.session_headers
                if item[0] == 'Authorization'
            ]
            browser.login(userid)

        transaction.commit()

        @contextmanager
        def login_context_manager():
            try:
                yield
            finally:
                setSecurityManager(security_manager)
                if browser is not None:
                    browser.clear_request_header('Authorization')
                    [browser.append_request_header(name, value)
                     for (name, value) in browser_auth_headers]
                transaction.commit()

        return login_context_manager()

    @property
    def directory(self):
        return self.layer['temp_directory']

    @contextmanager
    def package_created(self):
        with create(self.package).zcml_loaded(self.layer['configurationContext']) as package:
            yield package

    def default_upgrade(self):
        return Builder('plone upgrade step').upgrading('1000', to='1001')

    def install_profile(self, profileid, version=None):
        self.portal_setup.runAllImportStepsFromProfile(f'profile-{profileid}')
        if version is not None:
            self.portal_setup.setLastVersionForProfile(
                profileid, (str(version),))
        transaction.commit()

    def install_profile_upgrades(self, *profileids, **kwargs):
        intermediate_commit = kwargs.pop('intermediate_commit', False)

        gatherer = queryAdapter(self.portal_setup, IUpgradeInformationGatherer)
        upgrade_info = [
            (profile['id'], list(map(itemgetter('id'), profile['upgrades'])))
            for profile in gatherer.get_upgrades()
            if profile['id'] in profileids
        ]
        executioner = queryAdapter(self.portal_setup, IExecutioner)
        executioner.install(
            upgrade_info, intermediate_commit=intermediate_commit
        )

    def record_installed_upgrades(self, profile, *destinations):
        profile = re.sub('^profile-', '', profile)
        recorder = getMultiAdapter((self.portal, profile), IUpgradeStepRecorder)
        recorder.clear()
        list(map(recorder.mark_as_installed, destinations))
        transaction.commit()

    def clear_recorded_upgrades(self, profile):
        profile = re.sub('^profile-', '', profile)
        recorder = getMultiAdapter((self.portal, profile), IUpgradeStepRecorder)
        recorder.clear()
        transaction.commit()

    def assert_gathered_upgrades(self, expected, *args, **kwargs):
        gatherer = queryAdapter(self.portal_setup, IUpgradeInformationGatherer)
        result = gatherer.get_profiles(*args, **kwargs)
        got = {}
        for profile in result:
            if profile['id'] not in expected:
                continue

            got_profile = {key: [] for key in expected[profile['id']].keys()}
            got[profile['id']] = got_profile

            for upgrade in profile['upgrades']:
                for key in got_profile.keys():
                    if upgrade[key]:
                        got_profile[key].append(upgrade['sdest'])

        self.maxDiff = None
        self.assertDictEqual(
            expected, got,
            'Unexpected gatherer result.\n\nPackages in result {}:'.format(
                [profile['id'] for profile in result]))

    def asset(self, filename):
        return Path(__file__).dirname().joinpath('assets', filename).read_text()

    @contextmanager
    def assert_bundles_combined(self):
        # Note: this is for Plone 5.

        def get_timestamp():
            timestamp_file = self.portal.portal_resources.resource_overrides.production['timestamp.txt']
            # The data contains text, which should be a DateTime.
            # Convert it to an actual DateTime object so we can be sure when comparing it.
            return DateTime(timestamp_file.data.decode('utf8'))

        timestamp = get_timestamp()
        yield
        self.assertLess(timestamp, get_timestamp(),
                        'Timestamp has not been updated.')

    def setup_logging(self):
        self.log = StringIO()
        self.loghandler = logging.StreamHandler(self.log)
        self.logger = logging.getLogger('collective.ftw.upgrade')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.loghandler)

    def teardown_logging(self):
        if getattr(self, 'log', None) is None:
            return

        self.logger.removeHandler(self.loghandler)
        self.log = None
        self.loghandler = None
        self.logger = None

    def get_log(self):
        return truncate_memory_and_duration(self.log.getvalue().splitlines())

    def purge_log(self):
        self.log.seek(0)
        self.log.truncate()


class CommandTestCase(TestCase):
    layer = COMMAND_LAYER

    def upgrade_script(self, args, assert_exitcode=True):
        command = ' '.join(('upgrade', args))
        exitcode, output = self.layer['execute_script'](
            command, assert_exitcode=assert_exitcode)

        output = (re.compile(r'/[^\n]*Terminal kind \'dumb\'[^\n]*\n', re.M)
                  .sub('', output))
        output = (re.compile(r'^[^\n]*_BINTERM_UNSUPPORTED[^\n]*\n', re.M)
                  .sub('', output))
        return exitcode, output


class WorkflowTestCase(TestCase, AssertMixin):

    layer = UPGRADE_FUNCTIONAL_TESTING

    def setUp(self):
        self.portal = self.layer['portal']
        setRoles(self.portal, TEST_USER_ID, ['Manager'])

    def assertReviewStates(self, expected):
        wftool = getToolByName(self.portal, 'portal_workflow')

        got = {}
        for obj in expected.keys():
            review_state = wftool.getInfoFor(obj, 'review_state')
            got[obj] = review_state

        self.assertEqual(
            expected, got, 'Unexpected workflow states')

    def set_workflow_chain(self, for_type, to_workflow):
        wftool = getToolByName(self.portal, 'portal_workflow')
        wftool.setChainForPortalTypes((for_type,),
                                      (to_workflow,))

    def assertSecurityIsUpToDate(self):
        wftool = getToolByName(self.portal, 'portal_workflow')
        updated_objects = wftool.updateRoleMappings()
        self.assertEqual(
            0, updated_objects,
            'Expected all objects to have an up to date security, but'
            ' there were some which were not up to date.')

    def get_allowed_roles_and_users(self, for_object):
        processQueue()  # trigger async indexing
        catalog = getToolByName(self.portal, 'portal_catalog')
        path = '/'.join(for_object.getPhysicalPath())
        rid = catalog.getrid(path)
        index_data = catalog.getIndexDataForRID(rid)
        return index_data.get('allowedRolesAndUsers')

    def create_placeful_workflow_policy(self, named, with_workflows):
        placeful_wf_tool = getToolByName(
            self.portal, 'portal_placeful_workflow')

        placeful_wf_tool.manage_addWorkflowPolicy(named)
        policy = placeful_wf_tool.get(named)

        for portal_type, workflow in with_workflows.items():
            policy.setChain(portal_type, workflow)

        return policy

    def assert_permission_acquired(self, permission, obj, msg=None):
        not_acquired_permissions = self.get_not_acquired_permissions_of(obj)

        self.assertNotIn(
            permission, not_acquired_permissions,
            'Expected permission "{}" to be acquired on {}{}'.format(
                permission, str(obj),
                msg and (' (%s)' % msg) or ''))

    def assert_permission_not_acquired(self, permission, obj, msg=None):
        not_acquired_permissions = self.get_not_acquired_permissions_of(obj)

        self.assertIn(
            permission, not_acquired_permissions,
            'Expected permission "{}" to NOT be acquired on {}{}'.format(
                permission, str(obj),
                msg and (' (%s)' % msg) or ''))

    def get_not_acquired_permissions_of(self, obj):
        acquired_permissions = [
            item for item in obj.permission_settings() if not item.get('acquire')]

        return [item.get('name') for item in acquired_permissions]


class JsonApiTestCase(UpgradeTestCase):

    def setUp(self):
        super().setUp()
        self.portal_url = self.portal.absolute_url()
        self.api_session = RelativeSession(self.portal_url, test=self)

    def tearDown(self):
        super().tearDown()
        self.api_session.close()

    def assert_json_equal(self, expected, got, msg=None):
        expected = json.dumps(expected, sort_keys=True, indent=4)
        got = json.dumps(got, sort_keys=True, indent=4)
        self.maxDiff = None
        self.assertMultiLineEqual(expected, got, msg)

    def assert_json_contains_profile(self, expected_profileinfo, got, msg=None):
        profileid = expected_profileinfo['id']
        got_profiles = {profile['id']: profile for profile in got}
        self.assertIn(profileid, got_profiles,
                      'assert_json_contains_profile: expected profile not in JSON')
        self.assert_json_equal(expected_profileinfo, got_profiles[profileid], msg)

    def assert_json_contains(self, expected_element, got_elements):
        message = 'Could not find:\n\n{0}\n\nin list:\n\n{0}'.format(
            json.dumps(expected_element, sort_keys=True, indent=4),
            json.dumps(got_elements, sort_keys=True, indent=4))
        self.assertTrue(expected_element in got_elements, message)

    def is_installed(self, profileid, dest_time):
        recorder = getMultiAdapter((self.portal, profileid), IUpgradeStepRecorder)
        return recorder.is_installed(dest_time.strftime(scaffold.DATETIME_FORMAT))

    def html_request(self, method, path, data=None, authenticate=True):
        response = None
        if authenticate:
            self.api_session.auth = (SITE_OWNER_NAME, SITE_OWNER_PASSWORD)
        else:
            self.api_session.auth = None

        if method.lower() == 'get':
            response = self.api_session.get(path)
        elif method.lower() == 'post':
            if not data:
                data = {'enforce': 'post'}
            response = self.api_session.post(path, data=data)
        else:
            raise Exception(f'Unsupported request method {method}')
        return response

    def api_request(self, method, action, data=(), authenticate=True, context=None):
        self.api_session.headers.update({"Accept": "application/json"})

        url = ''
        response = None
        if context is not None:
            url = context.absolute_url()

        if authenticate:
            self.api_session.auth = (SITE_OWNER_NAME, SITE_OWNER_PASSWORD)
        else:
            self.api_session.auth = None

        if method.lower() == 'get':
            response = self.api_session.get('{}/upgrades-api/{}?{}'.format(
                url, action, six.moves.urllib.parse.urlencode(data)))

        elif method.lower() == 'post':
            if not data:
                data = {'enforce': 'post'}
            response = self.api_session.post(
                f'{url}/upgrades-api/{action}',
                data=data)
        else:
            raise Exception(f'Unsupported request method {method}')
        return response

    @contextmanager
    def expect_api_error(self, status=None, message=None, details=None):
        result = {}
        yield result

        if result['response'].status_code != status:
            raise AssertionError(
                'Expected HTTP error with status code {}, got {}.'.format(
                        status, result['response'].status_code))

        expected = {'result': 'ERROR'}
        if message is not None:
            expected['message'] = message
        if details is not None:
            expected['details'] = details

        got = dict(zip(['result', 'message', 'details'], result['response'].json()))

        self.assertDictContainsSubset(
            expected,
            got,
            'Unexpected error response details.\n\n'
            'Expected:' +
            json.dumps(expected, sort_keys=True, indent=4) +
            '\nto be included in:\n' +
            json.dumps(got, sort_keys=True, indent=4))

    def find_content(self, data, query, method='select_one'):
        soup = BeautifulSoup(data, 'html.parser')
        find = operator.methodcaller(method, query)
        return find(soup)


class CommandAndInstanceTestCase(JsonApiTestCase, CommandTestCase):
    layer = COMMAND_AND_UPGRADE_FUNCTIONAL_TESTING

    def setUp(self):
        super().setUp()
        self.directory.joinpath('var').mkdir_p()
        os.environ['UPGRADE_AUTHENTICATION'] = ':'.join((SITE_OWNER_NAME,
                                                         SITE_OWNER_PASSWORD))

    def tearDown(self):
        if 'UPGRADE_AUTHENTICATION' in os.environ:
            del os.environ['UPGRADE_AUTHENTICATION']
        if 'UPGRADE_PUBLIC_URL' in os.environ:
            del os.environ['UPGRADE_PUBLIC_URL']

    @property
    def directory(self):
        return self.layer['root_path']

    def write_zconf(self, instance_name, port):
        etc1 = self.layer['root_path'].joinpath('parts', instance_name, 'etc')
        etc1.makedirs()
        etc1.joinpath('zope.conf').write_text(
            '\n'.join(('<http-server>',
                       f'  address {port}',
                       '</http-server>')))
        return etc1.dirname()

    def write_zconf_with_test_instance(self):
        # Determine the port the ZServer layer has picked
        test_instance_port = self.layer['port']
        self.write_zconf('instance', test_instance_port)
