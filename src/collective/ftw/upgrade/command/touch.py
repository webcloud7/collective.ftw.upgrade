from collective.ftw.upgrade.command.terminal import TERMINAL
from collective.ftw.upgrade.directory.scaffold import DATETIME_FORMAT
from collective.ftw.upgrade.directory.scanner import UPGRADESTEP_DATETIME_REGEX
from datetime import datetime
from datetime import timedelta
from path import Path

import argparse
import re
import sys


DOCS = """
{t.bold}DESCRIPTION:{t.normal}
    Update the order of upgrades on the filesystem by changing the \
timestamps of the upgrades. \
This only works with new-style upgrades created with the "create" \
command and used with the "upgrade-step:directory" \
directive.

{t.bold}MOVE TO END:{t.normal}
    By just touching an upgrade it moves to the end of the chain and \
receives the current time as timestamp:
[quote]
$ bin/upgrade touch src/my/package/upgrades/20110101000000_foo
[/quote]

{t.bold}MOVE UPRADE BETWEEN OTHER UPGRADES:{t.normal}
    An upgrade can be moved to a specific position other upgrades by \
using the "--before" or "--after" optional arguments:
[quote]
$ bin/upgrade touch ...upgrades/20110101000000_foo --after \
...upgrades/20120202000000_bar
$ bin/upgrade touch ...upgrades/20110101000000_foo --before \
...upgrades/20120202000000_bar
[/quote]


""".format(t=TERMINAL).strip()


NAME_RE = re.compile(r'^.*/?\d{14}_([^/]*)$')
TIMESTAMP_RE = re.compile(r'^.*/?(\d{14})_[^/]*$')


def setup_argparser(commands):
    command = commands.add_parser(
        'touch',
        help='Update the timestamp of an existing upgrade step.',
        description=DOCS)
    command.set_defaults(func=touch_command)

    command.add_argument('path',
                         help='Path to the upgrade step directory to touch.',
                         type=upgrade_step_path)

    order = command.add_mutually_exclusive_group()
    order.add_argument('--after', '-a',
                       metavar='path',
                       dest='after_path',
                       help='Move after this upgrade step directory.',
                       type=upgrade_step_path)

    order.add_argument('--before', '-b',
                       metavar='path',
                       dest='before_path',
                       help='Move before this upgrade step directory.',
                       type=upgrade_step_path)


def touch_command(args):

    parents = set(map(Path.dirname,
                      filter(bool, (args.path,
                                    args.after_path,
                                    args.before_path))))
    if len(parents) > 1:
        print('ERROR: All paths must be in the same directory, got:',
              file=sys.stderr)
        for parent in parents:
            print('-', parent)
        sys.exit(1)

    new_date = find_new_date(args)
    new_name = NAME_RE.sub(
        fr'{new_date.strftime(DATETIME_FORMAT)}_\1',
        args.path.name)
    new_path = args.path.dirname().joinpath(new_name)
    args.path.rename(new_path)
    print('New path:', new_path)


def upgrade_step_path(path):
    path = Path(path).absolute()

    if not path.is_dir():
        raise argparse.ArgumentTypeError(
            f'"{path}" does not exist or is not a directory')

    if not path_to_datetime(path):
        raise argparse.ArgumentTypeError(
            '"{}" has not a valid upgrade step name or does'
            ' not contain an upgrade.py.'.format(path.name))

    return path


def find_new_date(args):
    before = path_to_datetime(args.before_path)
    after = path_to_datetime(args.after_path)
    if not before and not after:
        return datetime.now()

    upgrades = sorted(
        [_f for _f in map(path_to_datetime,
                          Path(args.path.dirname()).glob('*/upgrade.py'))
         if _f])
    upgrades.remove(path_to_datetime(args.path))

    if after and upgrades[-1] == after:
        return after + timedelta(days=1)

    if before and upgrades[0] == before:
        return before - timedelta(days=1)

    if not before:
        before = upgrades[upgrades.index(after) + 1]

    if not after:
        after = upgrades[upgrades.index(before) - 1]

    return after + (before - after) / 2


def path_to_datetime(path):
    if path is None:
        return None

    if not path.name == 'upgrade.py':
        path = path.joinpath('upgrade.py')

    match = UPGRADESTEP_DATETIME_REGEX.match(path)
    if not match:
        return None

    return datetime.strptime(match.group(1), '%Y%m%d%H%M%S')
