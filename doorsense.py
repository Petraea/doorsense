#!/usr/bin/env python
##########
#Replacement for Spacebot to write the SpaceAPI entry
#Large chunks of the doorsense code blatantly ripped from irccat.py by Bart Thate.
##########

## jsb imports

from jsb.lib.threads import start_new_thread
from jsb.lib.persist import PlugPersist
from jsb.lib.fleet import getfleet
from jsb.lib.commands import cmnds
from jsb.lib.examples import examples
from jsb.lib.callbacks import callbacks
from jsb.lib.threadloop import ThreadLoop

from jsb.plugs.common.topic import checktopicmode
from jsb.plugs.socket.mpd import mpd
from lights import lightprofile_activate

## basic imports

import json
import logging
import time
import SocketServer
from SocketServer import ThreadingMixIn, StreamRequestHandler

## defines

tcppassword = PlugPersist('tcppassword')
APIFILE = '/mnt/spaceapi/status.json'

cfg = PlugPersist("doorsense")
#{
#    "botnames": ["default-sxmpp",],
#    "host": "",
#    "port": "55555",
#    "aliases": {},
#    "password":"",
#    "enable": True,
#    })

sensorlist = PlugPersist('sensorlist', {
    'front_door':'Unknown',
    'back_door':'Unknown' })

statussensors = PlugPersist('statussensors', {'front_door':'Locked','back_door':'Locked'})

shared_data = {}
server = None
outputthread = None

## dummy callbacks to make sure plugin gets loaded on startup
def dummycb(bot, event): pass
callbacks.add("START", dummycb)

def apiSensors():
    return []

def apiupdate(openStatus=False):
    api = {"api":"0.12","space":"NURDSpace",
    "logo":"http://nurdspace.nl/spaceapi/logo.png",
    "icon":{"open":"http://nurdspace.nl/spaceapi/icon-open.png",
    "closed":"http://nurdspace.nl/spaceapi/icon-closed.png"},
    "url":"http://nurdspace.nl/",
    "address":"Churchillweg 68, 6706 AD Wageningen, The Netherlands",
    "contact":{"irc":"irc://irc.oftc.net/#nurds",
    "twitter":"@NURDspace",
    "ml":"nurds@nurdspace.nl"},
    "cam":["http://space.nurdspace.nl/video/channel_0.gif"],
    "lat":51.973276,
    "lon":5.672886,
    "open":openStatus,
    "lastchange":int(time.time()),
    "sensors":apiSensors()
    }

    try:
        with open('/mnt/spaceapi/status.json','w') as apifile:
            json.dump(api,apifile,indent=1)
    except:
        pass

def doorsense_output(msg):
    if msg[:len(tcppassword.data['password'])] == tcppassword.data['password']:
        msg = msg[len(tcppassword.data['password']):]
        sensor, value = tuple(msg.split(':'))
        fleet = getfleet()
        for botname in fleet.list():
            bot = fleet.byname(botname)
            if bot:
                bot.say('#nurds',sensor+' is '+value)
        if sensor in sensorlist.data.keys():
            sensorlist.data[sensor] = value
            sensorlist.save()
            statuscheck()

## doorsenseOutputThread

class doorsenseOutputThread(ThreadLoop):

    def handle(self, msg):
        doorsense_output(msg)

## doorsenseListener class

class doorsenseListener(ThreadingMixIn, StreamRequestHandler):

    def handle(self):
        msg = self.rfile.readline().strip()
        logging.warn("received %s" % msg)
        if outputthread and msg: outputthread.put(5, msg)        



## plugin initialisation

def init_threaded():
    global server
    global outputthread
    if server: logging.warn("doorsense server is already running.") ; return
    if not cfg.data.enable: logging.warn("doorsense is not enabled.") ; return 
    time.sleep(3)
    if "host" not in cfg.data or "port" not in cfg.data:
        cfg.data["host"] = ""
        cfg.data["port"] = 55555
        cfg.data["botnames"] = ["default-sxmpp",]
        tcppassword.data['password']='777'
        tcppassword.save()
        cfg.save()
    try:
        server = SocketServer.TCPServer((cfg.data["host"], int(cfg.data["port"])), doorsenseListener)
    except Exception, ex: logging.error(str(ex)) ; return
    logging.warn("starting doorsense server on %s:%s" % (cfg.data["host"], cfg.data["port"]))
    start_new_thread(server.serve_forever, ())
    outputthread = doorsenseOutputThread()
    outputthread.start()

def shutdown():
    global server
    if server:
        logging.warn("shutting down the doorsense server")
        server.shutdown()
    if outputthread: outputthread.stop()


def statuscheck():
    openstatus = False
    for sensor in sensorlist.data:
        if sensor in statussensors.data:
            if sensorlist.data[sensor] != statussensors.data[sensor]:
                openstatus=True
    topicset(openstatus)
    mpdset(openstatus)
    apiupdate(openstatus)

def topicset(state):
    retval = None
    fleet = getfleet()
    for botname in fleet.list():
        bot = fleet.byname(botname)
        if bot:
            topicdata = bot.gettopic('#nurds')
            if not topicdata: bot.say('#nurds',"can't get topic data, but the status should be toggled to "+str(state)+'!') ; return
    splitted = topicdata[0].split(' | ')
    statusline = splitted[0]
    if 'Space is ' in statusline:
        del splitted[0]
    if state:
        splitted.insert(0,'Space is OPEN')
        retval = True
    else:
        splitted.insert(0,'Space is CLOSED')
        retval = False
    newtopic = ' | '.join(splitted)
    for botname in fleet.list():
        bot = fleet.byname(botname)
        if bot and newtopic != topicdata[0]:
            bot.settopic('#nurds', newtopic)
    return retval

def mpdset(state):
    mpdstats = mpd('status') #list of tuples
    for x, y in mpdstats:
        if x == 'state': mpdstate = y
    if state:
        if mpdstate == 'play': mpd('pause')
    else:
        if mpdstate == 'pause': mpd('play')

def lightset(state):
    if state:
        lightprofile_activate('on')
    else:
        lightprofile_activate('off')

def handle_statustoggle(bot, ievent):
    topicdata = bot.gettopic(ievent.channel)
    if not topicdata: ievent.reply("can't get topic data") ; return
    splitted = topicdata[0].split(' | ')
    statusline = splitted[0]
#    if 'Space is ' in statusline:
#        del splitted[0]
    if statusline == 'Space is OPEN':
        topicset(False)
        mpdset(False)
        apiupdate(False)
        lightset(False)
    else:
        topicset(True)
        mpdset(True)
        apiupdate(True)
        lightset(True)

cmnds.add('statustoggle', handle_statustoggle, 'SPACE', threaded=True)
examples.add('statustoggle', 'Toggles the space status', 'statustoggle')

def handle_doorsense_enable(bot, event):
    cfg.data.enable = True ; cfg.save() ; event.done()
    init_threaded()
    
cmnds.add("doorsense-enable", handle_doorsense_enable, "OPER")
examples.add("doorsense-enable", "enable doorsense server", "doorsense-enable")

def handle_doorsense_disable(bot, event):
    cfg.data.enable = False ; cfg.save() ; event.done()
    shutdown()
    
cmnds.add("doorsense-disable", handle_doorsense_disable, "OPER")
examples.add("doorsense-disable", "disable doorsense server", "doorsense-disable")

