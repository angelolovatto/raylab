"""NN architecture used in Soft Actor-Critic."""
from dataclasses import dataclass
from dataclasses import field

import torch.nn as nn
from dataclasses_json import DataClassJsonMixin
from gym.spaces import Box

from .networks.actor.stochastic import StochasticActor
from .networks.critic.action_value import ActionValueCritic

ActorSpec = StochasticActor.spec_cls
CriticSpec = ActionValueCritic.spec_cls


@dataclass
class SACSpec(DataClassJsonMixin):
    """Specifications for SAC modules

    Args:
        actor: Specifications for stochastic policy and entropy coefficient
        critic: Specifications for action-value estimators
        initializer: Optional dictionary with mandatory `type` key corresponding
            to the initializer function name in `torch.nn.init` and optional
            keyword arguments.
    """

    actor: ActorSpec = field(default_factory=ActorSpec)
    critic: CriticSpec = field(default_factory=CriticSpec)
    initializer: dict = field(default_factory=dict)


class SAC(nn.Module):
    """NN module for Soft Actor-Critic algorithms.

    Args:
        obs_space: Observation space
        action_space: Action space
        spec: Specifications for SAC modules

    Attributes:
        actor (StochasticPolicy): Stochastic policy to be learned
        alpha (Alpha): Entropy bonus coefficient
        critics (QValueEnsemble): The action-value estimators to be learned
        target_critics (QValueEnsemble): The action-value estimators used for
            bootstrapping in Q-Learning
        spec_cls: Expected class of `spec` init argument
    """

    # pylint:disable=abstract-method
    spec_cls = SACSpec

    def __init__(self, obs_space: Box, action_space: Box, spec: SACSpec):
        super().__init__()
        # Top-level initializer options take precedence over individual
        # component's options
        if spec.initializer:
            spec.actor.initializer = spec.initializer
            spec.critic.initializer = spec.initializer

        actor = StochasticActor(obs_space, action_space, spec.actor)
        self.actor = actor.policy
        self.alpha = actor.alpha

        critic = ActionValueCritic(obs_space, action_space, spec.critic)
        self.critics = critic.q_values
        self.target_critics = critic.target_q_values
