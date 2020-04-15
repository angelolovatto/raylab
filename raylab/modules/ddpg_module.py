"""Actor-Critic architecture popularized by DDPG."""
from ray.rllib.utils import deep_update

from .abstract import AbstractActorCritic
from .mixins import ActionValueMixin, DeterministicActorMixin


BASE_CONFIG = {
    "torch_script": False,
    "actor": {
        # === Twin Delayed DDPG (TD3) tricks ===
        # Add gaussian noise to the action when calculating the Deterministic
        # Policy Gradient
        "smooth_target_policy": True,
        # Additive Gaussian i.i.d. noise to add to actions inputs to target Q function
        "target_gaussian_sigma": 0.3,
        "separate_target_policy": False,
        "perturbed_policy": False,
        # === SQUASHING EXPLORATION PROBLEM ===
        # Maximum l1 norm of the policy's output vector before the squashing
        # function
        "beta": 1.2,
        "encoder": {
            "units": (400, 300),
            "activation": "ReLU",
            "initializer_options": {"name": "xavier_uniform"},
            "layer_norm": False,
        },
    },
    "critic": {
        "double_q": False,
        "encoder": {
            "units": (400, 300),
            "activation": "ReLU",
            "initializer_options": {"name": "xavier_uniform"},
            "delay_action": True,
        },
    },
}


class DDPGModule(DeterministicActorMixin, ActionValueMixin, AbstractActorCritic):
    """Actor-Critic module with deterministic actor and action-value critics."""

    # pylint:disable=abstract-method

    def __init__(self, obs_space, action_space, config):
        config = deep_update(BASE_CONFIG, config, False, ["actor", "critic"])
        super().__init__(obs_space, action_space, config)
