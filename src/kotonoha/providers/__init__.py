"""Player providers (data sources) for Kotonoha.

Each provider emits normalized playback and lyric facts through application-owned
coordinators. Cider uses its local HTTP API; the generic adapter receiver accepts
versioned external-player messages, while MPRIS is an in-process D-Bus provider
for standard Linux media players.
"""
