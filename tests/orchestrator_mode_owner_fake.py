"""Storage fake for existing mode logic units, not Redis fencing evidence."""


def eval_mode_owner(self, script, number_of_keys, *arguments):
    assert "wolf15-mode-owner-v1" in script
    keys = arguments[:number_of_keys]
    action, token, _, channel, event, *values = arguments[number_of_keys:]
    leases = self.__dict__.setdefault("_mode_lease_tokens", {})
    if action == "acquire":
        if keys[0] in leases:
            return 0
        leases[keys[0]] = token
        return 1
    if leases.get(keys[0]) != token:
        return 0
    if action == "release":
        del leases[keys[0]]
    elif action == "write":
        for key, value in zip(keys[1:], values, strict=True):
            self.set(key, value)
        if channel:
            self.publish(channel, event)
    return 1
