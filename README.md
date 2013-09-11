This is the NURDbot's end of the sensor reading component.
It is in charge of updating the SpaceAPI, adjusting the MPD, controlling the lights
and adjusting the topic of the channel.

It has a small TCP server that listens for connections from servers. This should be
updated to the SpaceAPI for each update, but I haven't written that just yet. Any sensors
that should be in a state for the space to be closed are listed in a separate dictionary.
