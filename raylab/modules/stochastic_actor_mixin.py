"""Support for modules with stochastic policies."""
from typing import List

import torch
import torch.nn as nn
from ray.rllib.utils.annotations import override
import gym.spaces as spaces

from .basic import CategoricalParams, FullyConnected, NormalParams
from .distributions import (
    Categorical,
    Independent,
    Normal,
    TanhSquashTransform,
    TransformedDistribution,
)


class StochasticActorMixin:
    """Adds constructor for modules with stochastic policies."""

    # pylint:disable=too-few-public-methods

    @staticmethod
    def _make_actor(obs_space, action_space, config):
        actor_config = config["actor"]
        if isinstance(action_space, spaces.Discrete):
            return {"actor": CategoricalPolicy(obs_space, action_space, actor_config)}
        if isinstance(action_space, spaces.Box):
            return {"actor": GaussianPolicy(obs_space, action_space, actor_config)}
        raise ValueError(f"Unsopported action space type {type(action_space)}")


class MaximumEntropyMixin:
    """Adds entropy coefficient parameter to module."""

    # pylint:disable=too-few-public-methods

    def __init__(self, obs_space, action_space, config):
        super().__init__(obs_space, action_space, config)
        self.log_alpha = nn.Parameter(torch.zeros([]))


class StochasticPolicy(nn.Module):
    """Represents a stochastic policy as a conditional distribution module."""

    # pylint:disable=abstract-method

    @torch.jit.export
    def sample(self, obs, sample_shape: List[int] = ()):
        """
        Generates a sample_shape shaped sample or sample_shape shaped batch of
        samples if the distribution parameters are batched. Returns a (sample, log_prob)
        pair.
        """
        params = self(obs)
        return self.dist.sample(params, sample_shape)

    @torch.jit.export
    def rsample(self, obs, sample_shape: List[int] = ()):
        """
        Generates a sample_shape shaped reparameterized sample or sample_shape
        shaped batch of reparameterized samples if the distribution parameters
        are batched. Returns a (rsample, log_prob) pair.
        """
        params = self(obs)
        return self.dist.rsample(params, sample_shape)

    @torch.jit.export
    def log_prob(self, obs, action):
        """
        Returns the log of the probability density/mass function evaluated at `action`.
        """
        params = self(obs)
        return self.dist.log_prob(params, action)

    @torch.jit.export
    def cdf(self, obs, action):
        """Returns the cumulative density/mass function evaluated at `action`."""
        params = self(obs)
        return self.dist.cdf(params, action)

    @torch.jit.export
    def icdf(self, obs, prob):
        """Returns the inverse cumulative density/mass function evaluated at `prob`."""
        params = self(obs)
        return self.dist.icdf(params, prob)

    @torch.jit.export
    def entropy(self, obs):
        """Returns entropy of distribution."""
        params = self(obs)
        return self.dist.entropy(params)

    @torch.jit.export
    def perplexity(self, obs):
        """Returns perplexity of distribution."""
        params = self(obs)
        return self.dist.perplexity(params)

    @torch.jit.export
    def reproduce(self, obs, action):
        """Produce a reparametrized sample with the same value as `action`."""
        params = self(obs)
        return self.dist.reproduce(params, action)


class CategoricalPolicy(StochasticPolicy):
    """StochasticPolicy as a conditional Categorical distribution."""

    def __init__(self, obs_space, action_space, config):
        super().__init__()
        self.logits = _build_fully_connected(obs_space, config)
        self.params = CategoricalParams(self.logits.out_features, action_space.n)
        self.sequential = nn.Sequential(self.logits, self.params)
        self.dist = Categorical()

    @override(nn.Module)
    def forward(self, obs):  # pylint:disable=arguments-differ
        return self.sequential(obs)

    @torch.jit.export
    def mode(self, obs):
        """Compute most probable action."""
        params = self(obs)
        return torch.argmax(params["logits"], dim=-1)


class GaussianPolicy(StochasticPolicy):
    """StochasticPolicy as a conditional Gaussian distribution."""

    def __init__(self, obs_space, action_space, config):
        super().__init__()
        self.logits = _build_fully_connected(obs_space, config)
        self.params = NormalParams(
            self.logits.out_features,
            action_space.shape[0],
            input_dependent_scale=config["input_dependent_scale"],
        )
        self.sequential = nn.Sequential(self.logits, self.params)
        self.dist = TransformedDistribution(
            Independent(Normal(), reinterpreted_batch_ndims=1),
            TanhSquashTransform(
                low=torch.as_tensor(action_space.low),
                high=torch.as_tensor(action_space.high),
                event_dim=1,
            ),
        )

    @override(nn.Module)
    def forward(self, obs):  # pylint:disable=arguments-differ
        return self.sequential(obs)

    @torch.jit.export
    def mode(self, obs):
        """Compute most probable action."""
        params = self(obs)
        mode = params["loc"]
        base_log_prob = self.dist.base_dist.log_prob(params, mode)
        out, log_det = self.dist.transform(mode, {})
        return out, base_log_prob - log_det


def _build_fully_connected(obs_space, config):
    return FullyConnected(
        in_features=obs_space.shape[0],
        units=config["units"],
        activation=config["activation"],
        **config["initializer_options"],
    )