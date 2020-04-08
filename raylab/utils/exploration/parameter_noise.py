# pylint:disable=missing-docstring
# pylint:enable=missing-docstring
import torch
from ray.rllib.policy.sample_batch import SampleBatch
from ray.rllib.utils.annotations import override
from ray.rllib.utils.exploration import Exploration
from ray.rllib.utils.torch_ops import convert_to_non_torch_type

from raylab.modules.distributions import TanhSquashTransform
from raylab.utils.param_noise import AdaptiveParamNoiseSpec, ddpg_distance_metric
from raylab.utils.pytorch import perturb_module_params

from .random_uniform import RandomUniformMixin


class ParameterNoise(RandomUniformMixin, Exploration):
    """Adds adaptive parameter noise exploration schedule to a Policy.

    Args:
        param_noise_spec (Optional[dict]): Arguments for `AdaptiveParamNoiseSpec`.
    """

    def __init__(self, *args, param_noise_spec=None, **kwargs):
        super().__init__(*args, **kwargs)
        param_noise_spec = param_noise_spec or {}
        self._param_noise_spec = AdaptiveParamNoiseSpec(**param_noise_spec)
        self._squash = TanhSquashTransform(
            low=torch.as_tensor(self.action_space.low),
            high=torch.as_tensor(self.action_space.high),
        )

    @override(Exploration)
    def get_exploration_action(
        self, distribution_inputs, action_dist_class, model, timestep, explore=True,
    ):
        # pylint:disable=too-many-arguments
        if explore:
            if timestep < self._pure_exploration_steps:
                return super().get_exploration_action(
                    distribution_inputs, action_dist_class, model, timestep, explore
                )
            return model.behavior(distribution_inputs), None
        return model.actor(distribution_inputs), None

    @override(Exploration)
    def on_episode_start(self, policy, *, environment=None, episode=None, tf_sess=None):
        # pylint:disable=unused-argument
        perturb_module_params(
            policy.module.behavior,
            policy.module.actor,
            self._param_noise_spec.curr_stddev,
        )

    @torch.no_grad()
    @override(Exploration)
    def postprocess_trajectory(self, policy, sample_batch, tf_sess=None):
        self.update_parameter_noise(policy, sample_batch)
        return sample_batch

    @override(Exploration)
    def get_info(self):
        return {"param_noise_stddev": self._param_noise_spec.curr_stddev}

    def update_parameter_noise(self, policy, sample_batch):
        """Update parameter noise stddev given a batch from the perturbed policy."""
        module = policy.module
        cur_obs = policy.convert_to_tensor(sample_batch[SampleBatch.CUR_OBS])
        actions = policy.convert_to_tensor(sample_batch[SampleBatch.ACTIONS])
        target_actions = module.actor(cur_obs)
        unsquashed_acts, _ = self._squash(actions, reverse=True)
        unsquashed_targs, _ = self._squash(target_actions, reverse=True)

        noisy, target = map(
            convert_to_non_torch_type, (unsquashed_acts, unsquashed_targs)
        )
        distance = ddpg_distance_metric(noisy, target)
        self._param_noise_spec.adapt(distance)