# pylint: disable=missing-docstring,redefined-outer-name,protected-access
import pytest
import torch

from raylab.utils.debug import fake_batch


@pytest.fixture(params=((-1.0, -1.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 0.0)))
def bias(request):
    return request.param


@pytest.fixture(params=(0.0, 1.0))
def noise_sigma(request):
    return request.param


@pytest.fixture
def config(bias, noise_sigma):
    return {"true_model": True, "model_bias": bias, "model_noise_sigma": noise_sigma}


@pytest.fixture
def policy_and_env(mapo_policy, navigation_env, config):
    env = navigation_env({})
    policy = mapo_policy(env.observation_space, env.action_space, config)
    policy.set_reward_fn(env.reward_fn)
    policy.set_transition_fn(env.transition_fn)
    return policy, env


def test_model_output(policy_and_env):
    policy, env = policy_and_env
    obs = policy.observation_space.sample()[None]
    act = policy.action_space.sample()[None]
    obs, act = map(policy.convert_to_tensor, (obs, act))
    obs, act = map(lambda x: x.requires_grad_(True), (obs, act))

    torch.manual_seed(42)
    sample, logp = policy.module.model_sampler(obs, act)
    torch.manual_seed(42)
    next_obs, log_prob = env.transition_fn(obs, act)
    assert torch.allclose(sample, next_obs) or (
        policy.config["model_bias"] is not None or policy.config["model_noise_sigma"]
    )
    assert torch.allclose(logp, log_prob)
    assert sample.grad_fn is not None
    assert logp.grad_fn is not None


def test_madpg_loss(policy_and_env):
    policy, _ = policy_and_env
    batch = policy._lazy_tensor_dict(
        fake_batch(policy.observation_space, policy.action_space, batch_size=10)
    )

    loss, info = policy.compute_madpg_loss(batch, policy.module, policy.config)
    assert isinstance(info, dict)
    assert loss.shape == ()
    assert loss.dtype == torch.float32
    assert loss.grad_fn is not None

    policy.module.zero_grad()
    loss.backward()
    assert all(
        p.grad is not None
        and torch.isfinite(p.grad).all()
        and not torch.isnan(p.grad).all()
        for p in policy.module.policy.parameters()
    )