from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import re
from sys import version_info

import pytest
from py._path.local import LocalPath as Path
from testing import requirements
from testing import run
from testing import strip_coverage_warnings
from testing import TOP
from testing import uncolor
from testing import venv_update
from testing import venv_update_symlink_pwd
PY33 = (version_info >= (3, 3))


def test_trivial(tmpdir):
    tmpdir.chdir()
    requirements('')
    venv_update()


def enable_coverage(tmpdir):
    venv = tmpdir.join('virtualenv_run')
    if not venv.isdir():
        run('virtualenv', venv.strpath)
    run(
        venv.join('bin/python').strpath,
        '-m', 'pip.__main__',
        'install',
        '-r', TOP.join('requirements.d/coverage.txt').strpath,
    )


def install_twice(tmpdir, between):
    """install twice, and the second one should be faster, due to whl caching"""
    tmpdir.chdir()

    # Arbitrary packages that takes a bit of time to install:
    # Should I make a fixture c-extension to remove these dependencies?
    # NOTE: Avoid projects that use 2to3 (urwid). It makes the runtime vary too widely.
    requirements('''\
simplejson==3.6.5
pyyaml==3.11
pylint==1.4.0
logilab-common==0.63.2
astroid<1.3.3
py==1.4.26
pytest==2.6.4
unittest2==0.8.0
six<=1.8.0
chroniker
''')

    from time import time
    enable_coverage(tmpdir)
    assert pip_freeze() == '\n'.join((
        'cov-core==1.15.0',
        'coverage==4.0a1',
        ''
    ))

    start = time()
    venv_update()
    time1 = time() - start
    assert pip_freeze() == '\n'.join((
        'PyYAML==3.11',
        'astroid==1.3.2',
        'chroniker==0.0.0',
        'logilab-common==0.63.2',
        'py==1.4.26',
        'pylint==1.4.0',
        'pytest==2.6.4',
        'simplejson==3.6.5',
        'six==1.8.0',
        'unittest2==0.8.0',
        'wheel==0.24.0',
        ''
    ))

    between()

    start = time()
    # second install should also need no network access
    # these are localhost addresses with arbitrary invalid ports
    venv_update(
        http_proxy='http://127.0.0.1:111111',
        https_proxy='https://127.0.0.1:222222',
        ftp_proxy='ftp://127.0.0.1:333333',
    )
    time2 = time() - start
    assert pip_freeze() == '\n'.join((
        'PyYAML==3.11',
        'astroid==1.3.2',
        'chroniker==0.0.0',
        'logilab-common==0.63.2',
        'py==1.4.26',
        'pylint==1.4.0',
        'pytest==2.6.4',
        'simplejson==3.6.5',
        'six==1.8.0',
        'unittest2==0.8.0',
        'wheel==0.24.0',
        ''
    ))

    # second install should be at least twice as fast
    ratio = time1 / time2
    print('%.2fx speedup' % ratio)
    return ratio


@pytest.mark.flaky(reruns=2)
def test_noop_install_faster(tmpdir):
    def do_nothing():
        pass

    # constrain both ends, to show that we know what's going on
    # performance log: (clear when numbers become invalidated)
    #   2014-12-22 travis py26: 9.4-12
    #   2014-12-22 travis py27: 10-13
    #   2014-12-22 travis py34: 6-14
    #   2014-12-22 travis pypy: 5.5-7.5
    #   2015-01-07 linux py27: 17-34
    #   2015-02-17 travis pypy: 5.5-7.5
    assert 6 < install_twice(tmpdir, between=do_nothing) < 40


@pytest.mark.flaky(reruns=2)
def test_cached_clean_install_faster(tmpdir):
    def clean():
        venv = tmpdir.join('virtualenv_run')
        assert venv.isdir()
        venv.remove()
        assert not venv.exists()

    # I get ~4x locally, but only 2.5x on travis
    # constrain both ends, to show that we know what's going on
    # performance log: (clear when numbers become invalidated)
    #   2014-12-22 travis py26: 4-6
    #   2014-12-22 travis py27: 3.2-5.5
    #   2014-12-22 travis py34: 3.7-6
    #   2014-12-22 travis pypy: 3.5-4
    #   2014-12-24 travis pypy: 2.9-3.5
    #   2014-12-24 osx pypy: 3.9
    #   2015-09-05 travis pypy: 1.8-2.3  ## FIXME!
    assert 1.75 < install_twice(tmpdir, between=clean) < 7


def test_arguments_version(tmpdir):
    """Show that we can pass arguments through to virtualenv"""
    tmpdir.chdir()

    from subprocess import CalledProcessError
    with pytest.raises(CalledProcessError) as excinfo:
        # should show virtualenv version, then crash
        venv_update('--version')

    assert excinfo.value.returncode == 1
    out, err = excinfo.value.result
    err = strip_coverage_warnings(err)
    lasterr = err.rsplit('\n', 2)[-2]
    assert lasterr.startswith('virtualenv executable not found: /'), err
    assert lasterr.endswith('/virtualenv_run/bin/python'), err

    lines = [uncolor(line) for line in out.split('\n')]
    assert len(lines) == 3, lines
    assert lines[0].endswith(' -m virtualenv virtualenv_run --version'), repr(lines[0])


def test_arguments_system_packages(tmpdir):
    """Show that we can pass arguments through to virtualenv"""
    tmpdir.chdir()
    requirements('')

    venv_update('--system-site-packages', 'virtualenv_run', 'requirements.txt')

    out, err = run('virtualenv_run/bin/python', '-c', '''\
import sys
for p in sys.path:
    if p.startswith(sys.real_prefix) and p.endswith("-packages"):
        print(p)
        break
''')
    assert err == ''
    out = out.rstrip('\n')
    assert out and Path(out).isdir()


def pip_freeze():
    out, err = run('./virtualenv_run/bin/pip', 'freeze', '--local')

    # Most python distributions which have argparse in the stdlib fail to
    # expose it to setuptools as an installed package (it seems all but ubuntu
    # do this). This results in argparse sometimes being installed locally,
    # sometimes not, even for a specific version of python.
    # We normalize by never looking at argparse =/
    out = re.sub(r'argparse==[\d.]+\n', '', out, count=1)

    assert err == ''
    return out


def test_update_while_active(tmpdir):
    tmpdir.chdir()
    requirements('virtualenv<2')

    venv_update()
    assert 'mccabe' not in pip_freeze()

    # An arbitrary small package: mccabe
    requirements('virtualenv<2\nmccabe')

    venv_update_symlink_pwd()
    out, err = run('sh', '-c', '. virtualenv_run/bin/activate && python venv_update.py')

    assert err == ''
    assert out.startswith('Keeping virtualenv from previous run.\n')
    assert 'mccabe' in pip_freeze()


def test_update_invalidated_while_active(tmpdir):
    tmpdir.chdir()
    requirements('virtualenv<2')

    venv_update()
    assert 'mccabe' not in pip_freeze()

    # An arbitrary small package: mccabe
    requirements('virtualenv<2\nmccabe')

    venv_update_symlink_pwd()
    out, err = run('sh', '-c', '. virtualenv_run/bin/activate && python venv_update.py --system-site-packages')

    assert err == ''
    assert out.startswith('Removing invalidated virtualenv.\n')
    assert 'mccabe' in pip_freeze()


def test_eggless_url(tmpdir):
    tmpdir.chdir()
    requirements('')

    venv_update()
    assert 'venv-update' not in pip_freeze()

    # An arbitrary git-url requirement.
    requirements('git+git://github.com/Yelp/venv-update.git')

    venv_update()
    assert 'venv-update' in pip_freeze()


def test_scripts_left_behind(tmpdir):
    tmpdir.chdir()
    requirements('')

    venv_update()

    # an arbitrary small package with a script: pep8
    script_path = Path('virtualenv_run/bin/pep8')
    assert not script_path.exists()

    run('virtualenv_run/bin/pip', 'install', 'pep8')
    assert script_path.exists()

    venv_update()
    assert not script_path.exists()


def assert_timestamps(*reqs):
    firstreq = Path(reqs[0])
    lastreq = Path(reqs[-1])

    venv_update('--python=python', 'virtualenv_run', *reqs)

    assert firstreq.mtime() < Path('virtualenv_run').mtime()

    # garbage, to cause a failure
    lastreq.write('-w wat')

    from subprocess import CalledProcessError
    with pytest.raises(CalledProcessError) as excinfo:
        venv_update('virtualenv_run', *reqs)

    assert excinfo.value.returncode == 1
    assert firstreq.mtime() > Path('virtualenv_run').mtime()

    # blank requirements should succeed
    lastreq.write('')

    venv_update('virtualenv_run', *reqs)
    assert Path(reqs[0]).mtime() < Path('virtualenv_run').mtime()


def test_timestamps_single(tmpdir):
    tmpdir.chdir()
    requirements('')
    assert_timestamps('requirements.txt')


def test_timestamps_multiple(tmpdir):
    tmpdir.chdir()
    requirements('')
    Path('requirements2.txt').write('')
    assert_timestamps('requirements.txt', 'requirements2.txt')


def pipe_output(read, write):
    from os import environ
    environ = environ.copy()
    environ['HOME'] = str(Path('.').realpath())

    from subprocess import Popen
    vupdate = Popen(
        ('venv-update', '--version'),
        env=environ,
        stdout=write,
        close_fds=True,
    )

    from os import close
    from testing.capture_subprocess import read_all
    close(write)
    result = read_all(read)
    vupdate.wait()

    result = result.decode('US-ASCII')
    uncolored = uncolor(result)
    assert uncolored.startswith('> ')
    # FIXME: Sometimes this is 'python -m', sometimes 'python2.7 -m'. Weird.
    assert uncolored.endswith('''\
 -m virtualenv virtualenv_run --version
1.11.6
''')

    return result, uncolored


def test_colored_tty(tmpdir):
    tmpdir.chdir()

    from os import openpty
    read, write = openpty()

    from testing.capture_subprocess import pty_normalize_newlines
    pty_normalize_newlines(read)

    out, uncolored = pipe_output(read, write)

    assert out != uncolored


def test_uncolored_pipe(tmpdir):
    tmpdir.chdir()

    from os import pipe
    read, write = pipe()

    out, uncolored = pipe_output(read, write)

    assert out == uncolored


def test_args_backward(tmpdir):
    tmpdir.chdir()
    requirements('')

    from subprocess import CalledProcessError
    with pytest.raises(CalledProcessError) as excinfo:
        venv_update('requirements.txt', 'myvenv')

    # py26 doesn't have a consistent exit code:
    #   http://bugs.python.org/issue15033
    assert excinfo.value.returncode != 0
    _, err = excinfo.value.result
    lasterr = strip_coverage_warnings(err).rsplit('\n', 2)[-2]
    errname = 'NotADirectoryError' if PY33 else 'OSError'
    assert lasterr.startswith(errname + ': [Errno 20] Not a directory'), err

    assert Path('requirements.txt').isfile()
    assert Path('requirements.txt').read() == ''
    assert not Path('myvenv').exists()


def test_wrong_wheel(tmpdir):
    tmpdir.chdir()

    requirements('')
    venv_update('venv1', 'requirements.txt', '-ppython2.7')
    # A different python
    # Before fixing, this would install argparse using the `py2-none-any`
    # wheel, even on py3
    ret2out, _ = venv_update('venv2', 'requirements.txt', '-ppython3.3')

    assert 'py2-none-any' not in ret2out


def flake8_older():
    requirements('''\
flake8==2.0
# last pyflakes release before 0.8 was 0.7.3
pyflakes<0.8

# simply to prevent these from drifting:
mccabe<=0.3
pep8<=1.5.7
''')
    venv_update()
    assert pip_freeze() == '\n'.join((
        'flake8==2.0',
        'mccabe==0.3',
        'pep8==1.5.7',
        'pyflakes==0.7.3',
        'wheel==0.24.0',
        ''
    ))


def flake8_newer():
    requirements('''\
flake8==2.2.5
# we expect 0.8.1
pyflakes<=0.8.1

# simply to prevent these from drifting:
mccabe<=0.3
pep8<=1.5.7
''')
    venv_update()
    assert pip_freeze() == '\n'.join((
        'flake8==2.2.5',
        'mccabe==0.3',
        'pep8==1.5.7',
        'pyflakes==0.8.1',
        'wheel==0.24.0',
        ''
    ))


def test_upgrade(tmpdir):
    tmpdir.chdir()
    flake8_older()
    flake8_newer()


def test_downgrade(tmpdir):
    tmpdir.chdir()
    flake8_newer()
    flake8_older()


def test_remove_stale_cache_values(tmpdir):
    """Tests that we remove stale (older than a week) cached packages
    and wheels, while still keeping everything created within the past week.
    """
    import os
    import time

    tmpdir.chdir()
    home_path = str(Path('.').realpath())

    pip_path = home_path + '/.pip'
    cache_path = pip_path + '/cache'
    wheelhouse_path = pip_path + '/wheelhouse'

    stale_cached_package = cache_path + '/stale_package'
    fresh_cached_package = cache_path + '/new_package'

    stale_cached_wheel = wheelhouse_path + '/stale_wheel'
    fresh_cached_wheel = wheelhouse_path + '/new_wheel'

    # Creates a cached package and wheel in their respective
    # .pip/cache/ and .pip/wheelhouse directories.
    os.makedirs(stale_cached_package)
    os.makedirs(fresh_cached_package)
    os.makedirs(stale_cached_wheel)
    os.makedirs(fresh_cached_wheel)

    # Create some rough times for testing. These represent, in
    # seconds since epoch, a time from today, this week, and last month
    seconds_in_day = 86400
    today_time = int(time.time())
    this_week_time = int(time.time()) - seconds_in_day * 3
    last_month_time = int(time.time()) - seconds_in_day * 40

    # Set access times of stale package/wheel to be older than a week.
    os.utime(stale_cached_package, (0, 0))  # Jan 1, 1970
    os.utime(stale_cached_wheel, (last_month_time, last_month_time))

    # Set access times of fresh package/wheel to be within the past week.
    os.utime(fresh_cached_package, (today_time, today_time))
    os.utime(fresh_cached_wheel, (this_week_time, this_week_time))

    requirements('')
    venv_update()

    # Assert that we can no longer access the stale package/wheel
    # that have been removed.
    assert not os.access(stale_cached_package, os.F_OK)
    assert not os.access(stale_cached_wheel, os.F_OK)

    # Assert that we can still access the fresh package/wheel,
    # they should not have been removed.
    assert os.access(fresh_cached_package, os.F_OK)
    assert os.access(fresh_cached_wheel, os.F_OK)
