from collective.ftw.upgrade.browser.manage import ResponseLogger
from collective.ftw.upgrade.tests.base import JsonApiTestCase
from datetime import datetime
from ftw.builder import Builder
from io import BytesIO
from Products.CMFCore.utils import getToolByName
from unittest import TestCase

import logging
import re
import transaction


class TestResponseLogger(TestCase):

    def test_logging(self):
        response = BytesIO()

        with ResponseLogger(response):
            logging.error('foo')
            logging.error('bar')

        response.seek(0)
        self.assertEqual(
            [b'foo', b'bar'],
            response.read().strip().split(b'\n'))

    def test_logged_tags_get_escaped(self):
        response = BytesIO()

        with ResponseLogger(response):
            logging.error('ERROR: Something at <TextBlock at /bla/blub>')

        response.seek(0)
        self.assertEqual(
            [b'ERROR: Something at &lt;TextBlock at /bla/blub&gt;'],
            response.read().strip().split(b'\n'))

    def test_logging_exceptions(self):
        response = BytesIO()

        with self.assertRaises(KeyError):
            with ResponseLogger(response):
                raise KeyError('foo')

        response.seek(0)
        output = response.read().strip()
        # Dynamically replace paths so that it works on all machines
        output = re.sub(br'(File ").*(ftw/upgrade/.*")',
                        br'\1/.../\2', output)
        output = re.sub(br'(line )\d*', br'line XX', output)

        self.assertEqual(
            [b'FAILED',
             b'Traceback (most recent call last):',
             b'  File "/.../ftw/upgrade/tests/'
             b'test_manage_view.py", line XX, in test_logging_exceptions',
             b"    raise KeyError('foo')",
             b"KeyError: 'foo'"],
            output.split(b'\n'))

    def test_annotate_result_on_success(self):
        response = BytesIO()

        with ResponseLogger(response, annotate_result=True):
            logging.error('foo')
            logging.error('bar')

        response.seek(0)
        self.assertEqual(
            [b'foo', b'bar', b'Result: SUCCESS'],
            response.read().strip().split(b'\n'))

    def test_annotate_result_on_error(self):
        response = BytesIO()

        with self.assertRaises(KeyError):
            with ResponseLogger(response, annotate_result=True):
                raise KeyError('foo')

        response.seek(0)
        output = response.read().strip()
        # Dynamically replace paths so that it works on all machines
        output = re.sub(br'(File ").*(ftw/upgrade/.*")',
                        br'\1/.../\2', output)
        output = re.sub(br'(line )\d*', br'line XX', output)

        self.assertEqual(
            [b'FAILED',
             b'Traceback (most recent call last):',
             b'  File "/.../ftw/upgrade/tests/'
             b'test_manage_view.py", line XX, in test_annotate_result_on_error',
             b"    raise KeyError('foo')",
             b"KeyError: 'foo'",
             b'Result: FAILURE'],
            output.split(b'\n'))


class TestManageUpgrades(JsonApiTestCase):

    def setUp(self):
        super().setUp()
        self.portal_url = self.layer['portal'].portal_url()
        self.portal = self.layer['portal']

    def assertEqualURL(self, first, second, msg=None):
        # WebOb generates requests that always contain the port even for the
        # default port 80.
        return self.assertEqual(
            first.replace(':80', ''), second.replace(':80', ''), msg)

    def test_registered_in_controlpanel(self):
        response = self.html_request('GET', 'overview-controlpanel')
        link = self.find_content(response.content, '[href$="@@manage-upgrades"]')
        self.assertEqualURL(self.portal_url + '/@@manage-upgrades', link.attrs['href'])

    def test_manage_view_renders(self):
        response = self.html_request('GET', 'manage-upgrades')
        up_link = self.find_content(response.content, '.link-parent')
        self.assertEqualURL(self.portal_url + '/@@overview-controlpanel',
                            up_link.attrs['href'])

        self.assertTrue(
            self.find_content(response.content, 'input[value="plone.app.event:default"]'))

    def test_manage_plain_view_renders(self):
        response = self.html_request('GET', 'manage-upgrades-plain')
        self.assertTrue(
            self.find_content(response.content,'input[value="plone.app.event:default"]'))

    def test_manage_view_pre_selects_deferrable_upgrades(self):
        self.package.with_profile(
            Builder('genericsetup profile')
            .with_upgrade(Builder('ftw upgrade step')
                          .to(datetime(2011, 1, 1))
                          .as_deferrable()))

        with self.package_created():
            self.install_profile('the.package:default', version='1')
            self.clear_recorded_upgrades('the.package:default')
            transaction.commit()

            transaction.begin()  # sync transaction
            response = self.html_request('GET', 'manage-upgrades')
            deferrable_upgrade_checkbox = self.find_content(
                response.content, 'input[id|="the.package:default"]')
            self.assertEqual('checked', deferrable_upgrade_checkbox.attrs['checked'])

    def test_install(self):
        def upgrade_step(setup_context):
            portal = getToolByName(setup_context, 'portal_url').getPortalObject()
            portal.upgrade_installed = True

        self.package.with_profile(Builder('genericsetup profile')
                                  .with_upgrade(Builder('plone upgrade step')
                                                .upgrading('1111', '2222')
                                                .calling(upgrade_step, getToolByName)))

        with self.package_created():
            self.install_profile('the.package:default', '1111')
            self.portal.upgrade_installed = False
            transaction.commit()

            transaction.begin()  # sync transaction
            self.assertFalse(self.portal.upgrade_installed)

            response = self.html_request('GET', 'manage-upgrades')
            # Install proposed upgrades
            action = self.find_content(response.content, '[value="Install"]').parent.attrs['action']
            input_elements = self.find_content(response.content, 'input:checked', 'select')
            data = {element.attrs['name']: 'on' for element in input_elements}
            data['submitted'] = 'Install'
            data['upgrade.profileid:records'] = 'the.package:default'
            data['_authenticator'] = self.find_content(response.content, '[name="_authenticator"]').attrs['value']
            self.html_request('POST', action, data=data)

            transaction.begin()  # sync transaction
            self.assertTrue(self.portal.upgrade_installed)

    def test_upgrades_view_shows_cyclic_dependencies_error(self):
        self.package.with_profile(Builder('genericsetup profile')
                                  .named('foo')
                                  .with_dependencies('the.package:bar'))
        self.package.with_profile(Builder('genericsetup profile')
                                  .named('bar')
                                  .with_dependencies('the.package:foo'))

        with self.package_created():
            self.install_profile('the.package:foo')
            self.install_profile('the.package:bar')
            transaction.commit()

            response = self.html_request('GET', 'manage-upgrades')
            self.assertEqual(
                'Cyclic dependencies\nThere are cyclic dependencies. The profiles could not be sorted by dependencies!',
                self.find_content(response.content, '.portalMessage').text.strip()
            )

            possibilities = (
                ['the.package:foo', 'the.package:bar'],
                ['the.package:bar', 'the.package:foo'])

            dep = self.find_content(response.content, '.cyclic-dependencies li').text
            self.assertIn(re.findall(r'the\.package:\w+', dep), possibilities)
