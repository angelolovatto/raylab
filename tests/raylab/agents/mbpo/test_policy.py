import pytest

ENSEMBLE_SIZE = (1, 4)


@pytest.fixture(
    scope="module", params=ENSEMBLE_SIZE, ids=(f"Ensemble({s})" for s in ENSEMBLE_SIZE)
)
def ensemble_size(request):
    return request.param


@pytest.fixture(scope="module")
def config(ensemble_size):
    return {
        "model_training": {
            "dataloader": {"batch_size": 32, "replacement": False},
            "max_epochs": 10,
            "max_time": 4,
            "improvement_threshold": 0.01,
            "patience_epochs": 5,
        },
        "model_sampling": {"rollout_schedule": [(0, 10)], "num_elites": 1},
        "module": {"model": {"ensemble_size": ensemble_size}},
    }


@pytest.fixture(scope="module")
def policy(policy_cls, config):
    return policy_cls(config)


def test_policy_creation(policy):
    for attr in "models actor alpha critics".split():
        assert hasattr(policy.module, attr)

    assert "models" in policy.optimizers
    assert "actor" in policy.optimizers
    assert "critics" in policy.optimizers
    assert "alpha" in policy.optimizers
