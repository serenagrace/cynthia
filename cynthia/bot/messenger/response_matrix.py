ResponseMatrix = {
    "ping": lambda messenger, msg: messenger.send_msg(msg.channel, "pong"),
    "status": lambda messenger, msg: messenger.send_msg(
        msg.channel, repr(messenger.bot.status)
    ),
}
