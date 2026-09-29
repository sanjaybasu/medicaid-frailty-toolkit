import warnings

import pytest

from frailty_toolkit import load_state_config
from frailty_toolkit.synthetic import make_scenarios

AS_OF = "2027-01-01"


@pytest.fixture(scope="session")
def scenarios():
    return make_scenarios(AS_OF)


@pytest.fixture(scope="session")
def template_cfg():
    return load_state_config("template")


@pytest.fixture
def quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield
