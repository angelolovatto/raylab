import pytest
import torch
import torch.nn as nn
from ray.rllib import SampleBatch

import raylab.utils.dictionaries as dutil
from raylab.policy.losses import SoftCDQLearning


@pytest.fixture(params=(True, False))
def double_q(request):
    return request.param


@pytest.fixture
def policy_and_batch(policy_and_batch_fn, double_q):
    config = {"module": {"critic": {"double_q": double_q}}, "polyak": 0.5}
    return policy_and_batch_fn(config)


def loss_maker(policy):
    loss_fn = SoftCDQLearning(
        policy.module.critics,
        policy.module.target_critics,
        actor=policy.module.actor.sample,
    )
    loss_fn.gamma = policy.config["gamma"]
    loss_fn.alpha = policy.module.alpha().item()
    return loss_fn


def test_critic_targets(policy_and_batch):
    policy, batch = policy_and_batch
    loss_fn = loss_maker(policy)

    rewards, next_obs, dones = dutil.get_keys(
        batch, SampleBatch.REWARDS, SampleBatch.NEXT_OBS, SampleBatch.DONES
    )
    targets = loss_fn.critic_targets(rewards, next_obs, dones)
    assert targets.shape == (len(next_obs),)
    assert targets.dtype == torch.float32
    assert torch.allclose(targets[dones], batch[SampleBatch.REWARDS][dones])

    policy.module.zero_grad()
    targets.mean().backward()
    target_params = set(policy.module.target_critics.parameters())
    target_params.update(set(policy.module.actor.parameters()))
    assert all(p.grad is not None for p in target_params)
    assert all(p.grad is None for p in set(policy.module.parameters()) - target_params)


def test_critic_loss(policy_and_batch):
    policy, batch = policy_and_batch
    loss_fn = loss_maker(policy)

    loss, info = loss_fn(batch)
    assert loss.shape == ()
    assert loss.dtype == torch.float32
    assert isinstance(info, dict)

    params = set(policy.module.critics.parameters())
    loss.backward()
    assert all(p.grad is not None for p in params)
    assert all(p.grad is None for p in set(policy.module.parameters()) - params)

    obs, acts = dutil.get_keys(batch, SampleBatch.CUR_OBS, SampleBatch.ACTIONS)
    vals = [m(obs, acts) for m in policy.module.critics]
    concat_vals = torch.cat(vals, dim=-1)
    targets = torch.randn_like(vals[0])
    loss_fn = nn.MSELoss()
    assert torch.allclose(
        loss_fn(concat_vals, targets.expand_as(concat_vals)),
        sum(loss_fn(val, targets) for val in vals) / len(vals),
    )


def test_target_net_init(policy_and_batch):
    policy, _ = policy_and_batch
    params = list(policy.module.critics.parameters())
    target_params = list(policy.module.target_critics.parameters())
    assert all(torch.allclose(p, q) for p, q in zip(params, target_params))
