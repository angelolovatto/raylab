# pylint: disable=missing-docstring
# pylint: enable=missing-docstring
import gym
import torch
import numpy as np


DEFAULT_CONFIG = {
    "start": [-10.0, -10.0],
    "end": [10.0, 10.0],
    "action_lower_bound": [-1.0, -1.0],
    "action_upper_bound": [1.0, 1.0],
    "deceleration_zones": {"center": [[0.0, 0.0]], "decay": [2.0]},
    "noise": {"loc": [0.0, 0.0], "scale_tril": [[0.3, 0.0], [0.0, 0.3]]},
    "horizon": 20,
}


class NavigationEnv(gym.Env):
    """NavigationEnv implements a gym environment for the Navigation
    domain.

    The agent must navigate from a start position to and end position.
    Its actions represent displacements in the 2D plane. Gaussian noise
    is added to the final position as to incorporate uncertainty in the
    transition. Additionally, the effect of an action might be decreased
    by a scalar factor dependent on the proximity of deceleration zones.

    Please refer to the AAAI paper for further details:

    Bueno, T.P., de Barros, L.N., Mauá, D.D. and Sanner, S., 2019, July.
    Deep Reactive Policies for Planning in Stochastic Nonlinear Domains.
    In Proceedings of the AAAI Conference on Artificial Intelligence.
    """

    # pylint: disable=too-many-instance-attributes

    metadata = {"render.modes": ["human"]}

    def __init__(self, config=None):
        self._config = {**DEFAULT_CONFIG, **(config or {})}

        self._start = np.array(self._config["start"], dtype=np.float32)
        self._end = np.array(self._config["end"], dtype=np.float32)

        self.observation_space = gym.spaces.Box(
            low=np.array([-np.inf, -np.inf, 0.0], dtype=np.float32),
            high=np.array([np.inf, np.inf, 1.0], dtype=np.float32),
        )
        self.action_space = gym.spaces.Box(
            low=np.array(self._config["action_lower_bound"], dtype=np.float32),
            high=np.array(self._config["action_upper_bound"], dtype=np.float32),
        )

        self._deceleration_zones = self._config["deceleration_zones"]
        if self._deceleration_zones:
            self._deceleration_decay = np.array(
                self._deceleration_zones["decay"], dtype=np.float32
            )
            self._deceleration_center = np.array(
                self._deceleration_zones["center"], dtype=np.float32
            )

        self._noise = self._config["noise"]
        self._horizon = self._config["horizon"]
        self._state = None

    def reset(self):
        self._state = np.append(self._start, np.array(0.0, dtype=np.float32))
        return self._state

    def step(self, action):
        state, action = map(torch.as_tensor, (self._state, action))
        next_state = self.transition_fn(state, action)
        reward = self.reward_fn(state, action, next_state).numpy()
        self._state = next_state.numpy()
        return self._state, reward, self._terminal(), {}

    def _terminal(self):
        pos, time = self._state[:2], self._state[2]
        return np.allclose(pos, self._end, atol=1e-1) or np.allclose(time, 1.0)

    def reward_fn(self, state, action, next_state):
        # pylint: disable=unused-argument,missing-docstring
        next_state = next_state[:2]
        goal = torch.from_numpy(self._end)
        return torch.norm(next_state - goal, dim=-1).neg()

    def transition_fn(self, state, action):
        # pylint: disable=missing-docstring
        state, time = state[..., :2], state[..., 2:]
        deceleration = 1.0
        if self._deceleration_zones:
            deceleration = self._deceleration(state)

        position = state + (deceleration * action)
        next_state = self._sample_noise(position)
        return torch.cat([next_state, time + 1 / self._horizon], dim=-1)

    def _sample_noise(self, position):
        loc = position + torch.as_tensor(self._noise["loc"])
        scale_tril = torch.as_tensor(self._noise["scale_tril"])
        dist = torch.distributions.MultivariateNormal(loc=loc, scale_tril=scale_tril)
        return dist.sample()

    def _deceleration(self, state):
        decay = torch.from_numpy(self._deceleration_decay)
        center = torch.from_numpy(self._deceleration_center)
        distance = torch.norm(state - center, dim=-1)
        deceleration = torch.prod(2 / (1.0 + torch.exp(-decay * distance)) - 1.0)
        return deceleration

    def render(self, mode="human"):
        pass