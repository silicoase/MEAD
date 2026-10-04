import pytest

from mad.config import TaskConfig
from mad.objective_reference import objective_reference
from mad.task import SyntheticObjective


@pytest.mark.parametrize("seed,oracle", [(42, 0.6625406185776), (43, 0.6327997385691)])
def test_reference_brackets_independent_multistart_scipy_optimum(seed, oracle):
    # Independently obtained with eight differential-evolution searches of
    # the coupled coordinates and stationary-root searches of separable terms.
    config = TaskConfig(objective_seed=seed)
    reference = objective_reference(config)
    assert reference["estimated_maximum"] <= oracle + 1e-10
    assert oracle <= reference["upper_bound"] + 1e-10
    assert reference["bound_gap"] < 2e-5
    assert SyntheticObjective(config).evaluate(reference["maximizing_parameters"]) == (
        reference["estimated_maximum"]
    )


def test_reference_respects_physical_bounds_and_minimum_dimension():
    unit = objective_reference(TaskConfig(dimensions=3))
    scaled_config = TaskConfig(dimensions=3, lower=-2, upper=4)
    scaled = objective_reference(scaled_config)
    assert scaled["estimated_maximum"] == pytest.approx(unit["estimated_maximum"])
    assert scaled["maximizing_parameters"] == pytest.approx(
        [-2 + 6 * p for p in unit["maximizing_parameters"]]
    )
    assert len(scaled["maximizing_parameters"]) == 3
    assert scaled["upper_bound"] >= scaled["estimated_maximum"]
