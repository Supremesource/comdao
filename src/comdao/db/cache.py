from typing import Callable, TypeVar, ParamSpec, Coroutine, Any
from communex.types import Ss58Address
from threading import Lock
import json

class NominationVote(dict):
    def __init__(
            self, 
            module_key: Ss58Address, 
            recommended_weight: int
) -> None:
        self.module_key = module_key
        self.recommended_weight = recommended_weight
        dict.__init__(self, module_key=module_key, recommended_weight=recommended_weight)

    def default(self, o):
        print(o.__dict__)
        return o.__dict__
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            module_key=data['module_key'],
            recommended_weight=data['recommended_weight']
        )

    def __eq__(self, other):
        if isinstance(other, NominationVote):
            return self.module_key == other.module_key
        elif isinstance(other, str):
            return self.module_key == other
        else:
            return False
        
# TODO: make a singleton
class Cache:
    request_ids: list[Ss58Address] = []
    # discord_user_id : voted_ticket_id
    nomination_approvals: dict[str, list[NominationVote]] = {}
    removal_approvals: dict[str, list[Ss58Address]] = {}
    rejection_approvals: dict[str, list[Ss58Address]] = {}
    last_submission_times = {}
    current_whitelist: list[Ss58Address] = []
    dao_applications: list[str] = []


    def __init__(self) -> None:
        self._file_path = "./state.json"
        self.load_from_disk()
        self.lock = Lock()

    def save_to_disk(self):
            print("SAVING TO DISK")
            data = {
                'request_ids': json.dumps(self.request_ids),
                'nomination_approvals': json.dumps(self.nomination_approvals),
                'removal_approvals': json.dumps(self.removal_approvals),
                'rejection_approvals': json.dumps(self.rejection_approvals),
                'dao_applications': json.dumps(self.dao_applications),
            }
            with open(self._file_path, 'w') as file:
                json.dump(data, file)

    def load_from_disk(self):
        try:
            with open(self._file_path, 'r') as file:
                data = json.load(file)
                self.request_ids = json.loads(data['request_ids'])

                self.dao_applications = json.loads(data['dao_applications'])
                self.removal_approvals = json.loads(data['removal_approvals'])
                self.rejection_approvals = json.loads(data['rejection_approvals'])
                self.nomination_approvals = {}
                votes_dict = json.loads(data['nomination_approvals'])
                for user_id in votes_dict:
                    votes = [NominationVote.from_dict(vote) for vote in votes_dict[user_id]]
                    self.nomination_approvals[user_id] = votes
                    

        except FileNotFoundError:
            print("Could not find state file. Proceeding from scratch")

    def __enter__(self):
        self.lock.acquire()

    def __exit__(self, *args, **kwargs):
        self.lock.release()

CACHE = Cache()
T = TypeVar('T')
P = ParamSpec("P")
def save_state(cache: Cache):
    def decorator(func: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        async def wrapper(*args: P.args, **kwargs: P.kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                cache.save_to_disk()
        return wrapper
    return decorator

print(CACHE.dao_applications)
