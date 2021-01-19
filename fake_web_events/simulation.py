from datetime import date, datetime, timedelta
from random import randrange, choices, random, expovariate, triangular
from fake_web_events.event import Event
from fake_web_events.user import UserPool
from fake_web_events.utils import load_config
from time import time
import json

from typing import Generator


class Simulation():
    """
    Keep track of the simulation state
    """

    def __init__(
            self,
            user_pool_size: int,
            sessions_per_day: int = 10000,
            batch_size: int = 10,
            init_time: datetime = datetime.now(),
            sim_days=1,
            growth=None,
            config_path: str = None,
            always_forward=True,
            yield_as_json=False
    ):

        self.config = load_config(config_path)
        # self.config_path = config_path
        self.user_pool = UserPool(size=user_pool_size, config=self.config)
        self.cur_sessions = []
        self.init_time = init_time
        # time attributes
        self.cur_time = init_time
        assert sim_days > 0, "Simulation lenght cannot be negative"
        self.stop_time = init_time + timedelta(days=sim_days)
        self.batch_size = batch_size
        self.sessions_per_day = sessions_per_day
        self.qty_events = 0
        self.rate = self.get_rate_per_step()

        self.growth = growth
        self.always_forward = always_forward

        self.yield_as_json = yield_as_json

    def __str__(self) -> str:
        """
        Return human readable state
        """
        return "\nSIMULATION STATE\n" \
               f"Current Sessions: {self.get_len_sessions()}\n" \
               f"Current duration: {self.get_duration_str()}\n" \
               f"Current user rate: {self.rate}\n" \
               f"Quantity of events: {self.qty_events}"

    def get_len_sessions(self) -> int:
        """
        Calculate amount of current active sessions
        """
        return len(self.cur_sessions)

    def get_curr_duration(self) -> timedelta:
        """
        Get duration of simulation
        """
        return self.cur_time - self.init_time

    def get_duration_str(self) -> str:
        """
        Get simulation duration as a string
        """
        duration_td = self.get_curr_duration()
        days = duration_td.days
        hours = duration_td.seconds // 3600
        minutes = (duration_td.seconds // 60) % 60
        seconds = duration_td.seconds % 60
        return f'{days} days, {hours} hours, {minutes} minutes, {seconds} seconds'

    def get_steps_per_hour(self) -> float:
        """
        Calculate how many steps are there in one hour
        """
        return 3600 / self.batch_size

    def get_rate_per_step(self) -> float:
        """
        Calculate rate of events per step
        """
        hourly_rate = self.config['visits_per_hour'][self.cur_time.hour]
        return hourly_rate * self.sessions_per_day / self.get_steps_per_hour()

    def wait(self, always_forward: bool) -> None:
        """
        Wait for given amount of time defined in batch size
        """
        min_range = 0 if always_forward else - int(self.batch_size * 0.3)
        max_range = int(self.batch_size * 0.3)
        self.cur_time += timedelta(seconds=self.batch_size + randrange(min_range, max_range))
        self.rate = self.get_rate_per_step()

    def randomize_sess_ts(self) -> datetime:
        """
        Randomize timestamps so not all sessions come with the same current time
        """
        # Apply random growth according to specification
        # TODO allow more customization of growth parameters
        if self.growth in ['lineal', 'lin', 'linear']:  # linear distribution
            ratio = 1 - triangular(0, 1, 0)
        elif self.growth in ['exp', 'exponential']:  # exponential growth
            ratio = expovariate(1 / 1.5)
            ratio = (8 - ratio) / 8 if ratio < 8 else 1
        else:
            ratio = random()

        # randomize session timestamp
        return self.init_time + ratio * (self.stop_time - self.init_time)

    def create_sessions(self) -> list:
        """
        Create a new session for a new user
        """
        n_users = int(self.rate)
        n_users += choices([1, 0], cum_weights=[(self.rate % 1), 1])[0]
        for n in range(n_users):
            self.cur_sessions.append(Event(self.randomize_sess_ts(),
                                           self.user_pool.get_user(),
                                           self.batch_size,
                                           self.always_forward,
                                           self.config
                                           )
                                     )

        return self.cur_sessions

    def update_all_sessions(self) -> None:
        """
        Function to run one step of a simulation.
        """
        for session in list(self.cur_sessions):
            session.update(session.current_timestamp + self.get_curr_duration(), self.always_forward)
            if not session.is_active():
                self.cur_sessions.remove(session)

    def yield_event(self, session):
        """
        Function yield event depending if it is wanted as json or dict
        """
        if self.yield_as_json:
            return json.dumps(session.asdict(), default=json_serial)
        else:
            return session.asdict()

    def run(self, duration_seconds: int) -> Generator[dict, None, None]:
        """
        Function to run a simulation for the given duration in seconds. Yields events.
        """
        start = time()
        while time() - start < duration_seconds:
            self.update_all_sessions()
            self.create_sessions()
            self.wait(self.always_forward)
            for session in self.cur_sessions:
                if session.is_new_page:
                    # new pageview event
                    yield self.yield_event(session)
                elif not session.is_new_page and session.custom_event != 'pageview':
                    # custome events
                    if session.modal_event != session.custom_event:
                        # any custom event that is not the current modal
                        yield self.yield_event(session)
                    else:
                        # modal custom event (only when yield_modal)
                        # ^ indicates function XOR
                        if not (session.modal ^ session.yield_modal):
                            yield self.yield_event(session)


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))
