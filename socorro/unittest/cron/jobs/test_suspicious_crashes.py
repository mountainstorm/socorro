# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import json
import random

from nose.plugins.attrib import attr

from socorro.cron import crontabber
from socorro.lib.datetimeutil import utc_now
from ..base import TestCaseBase, IntegrationTestCaseBase

SQL_INSERT = """
INSERT INTO
    reports
    (uuid, signature, date_processed)
VALUES
    ({uuid}, '{signature}', '{date}'::timestamp without time zone)
"""


@attr(integration='postgres')  # for nosetests
class TestSuspiciousCrashAnalysisIntegration(IntegrationTestCaseBase):
    def setUp(self):
        super(TestSuspiciousCrashAnalysisIntegration, self).setUp()

        cursor = self.conn.cursor()
        now = utc_now()
        current = now - datetime.timedelta(15)

        # we want to generate 10 crashes for each day, +/- 1 crashes.
        uuid = 1
        while current < now:
            for i in xrange(random.randint(9, 11)):
                sql = SQL_INSERT.format(uuid=uuid,
                                        signature='sig',
                                        date=current.strftime('%Y-%m-%d'))
                cursor.execute(sql)
                uuid += 1

            current += datetime.timedelta(1)

        # today we want to generate some more crashes so we have an explosive
        # crash.
        for i in xrange(30):
            sql = SQL_INSERT.format(uuid=uuid,
                                    signature='sig',
                                    date=now.strftime('%Y-%m-%d'))
            cursor.execute(sql)
            uuid += 1

        self.conn.commit()

    def tearDown(self):
        super(TestSuspiciousCrashAnalysisIntegration, self).tearDown()
        self.conn.cursor().execute("""
            TRUNCATE TABLE reports, suspicious_crash_signatures;
        """)
        self.conn.commit()

    def _setup_config_manager(self, **kwargs):
        kwargs.setdefault('training_data_length', 10)
        kwargs.setdefault('data_bin_length', 10)
        kwargs.setdefault('model', 'SlopeBased')

        # This is the one we modified
        kwargs.setdefault('min_count', 5)

        evs = {}
        for k, v in kwargs.iteritems():
            evs['crontabber.class-SuspiciousCrashesApp.' + k] = v

        config_manager, json_file = super(
            TestSuspiciousCrashAnalysisIntegration,
            self
        )._setup_config_manager(
            'socorro.cron.jobs.suspicious_crashes.SuspiciousCrashesApp|1d',
            extra_value_source=evs
        )

        return config_manager, json_file

    def test_run(self):
        config_manager, json_file = self._setup_config_manager()

        with config_manager.context() as config:
            tab = crontabber.CronTabber(config)
            tab.run_all()

            information = json.load(open(json_file))
            assert information['suspicious-crashes']
            assert not information['suspicious-crashes']['last_error']
            assert information['suspicious-crashes']['last_success']

            cursor = self.conn.cursor()

            cursor.execute("""
                SELECT signature, date FROM suspicious_crash_signatures;
            """)

            count = 0
            today = utc_now().strftime('%Y-%m-%d')
            for row in cursor.fetchall():
                self.assertEquals('sig', row[0])
                self.assertEquals(today, row[1].strftime('%Y-%m-%d'))
                count += 1

            self.assertEquals(1, count)
