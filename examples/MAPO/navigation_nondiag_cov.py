from ray import tune
from ray.rllib.utils import merge_dicts

from navigation_base import get_config as base_config


def get_config():
    return merge_dicts(
        base_config(),
        {
            # === Environment ===
            "env_config": {
                "deceleration_zones": {"center": [[0.0, 0.0]], "decay": [2.0]},
                "noise": {"loc": [0.0, 0.0], "scale_tril": [[0.3, 0.0], [0.2, 0.3]]},
            },
            # === MAPO model training ===
            # Type of model-training to use. Possible types include
            # decision_aware: policy gradient-aware model learning
            # mle: maximum likelihood estimation
            "model_loss": tune.grid_search(["decision_aware", "mle"]),
            # Number of next states to sample from the model when calculating the
            # model-aware deterministic policy gradient
            "num_model_samples": 4,
            # Gradient estimator for model-aware dpg. Possible types include:
            # score_function, pathwise_derivative
            "grad_estimator": tune.grid_search(
                ["score_function", "pathwise_derivative"]
            ),
            # === Replay Buffer ===
            "buffer_size": int(4e4),
            # === Network ===
            # Size and activation of the fully connected networks computing the logits
            # for the policy and action-value function. No layers means the component is
            # linear in states and/or actions.
            "module": {
                "actor": {"encoder": {"units": (64,)}},
                "critic": {"encoder": {"units": (64,)}},
                "model": {"encoder": {"units": (10,)}},
            },
        },
    )
