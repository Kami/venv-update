from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from testing import strip_coverage_warnings
from testing import venv_update
from venv_update import __doc__ as HELP_OUTPUT


def test_help():
    assert HELP_OUTPUT
    assert HELP_OUTPUT.startswith('usage:')
    last_line = HELP_OUTPUT.rsplit('\n', 2)[-2].strip()
    assert last_line.startswith('Version control at: http')

    out, err = venv_update('--help')
    assert strip_coverage_warnings(err) == ''
    assert out == HELP_OUTPUT

    out, err = venv_update('-h')
    assert strip_coverage_warnings(err) == ''
    assert out == HELP_OUTPUT
