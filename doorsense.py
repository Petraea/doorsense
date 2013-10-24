#!/usr/bin/env python
# -*- coding: utf-8 -*-
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

testing = False

tcppassword = PlugPersist('tcppassword')

APIFILE = '/mnt/spaceapi/status.json'

cfg = PlugPersist("doorsense")

sensorlist = PlugPersist('sensorlist', {
#sensorlist.data = {
    'door_locked':[
        {'value':None,'location':'front_door','name':"front_door",'description':""},
        {'value':None,'location':'back_door','name':"back_door",'description':""}
    ],
    'temperature':[
        {'value':0.0,'unit':'°C','location':' ','name':' '},
        {'value':0.0,'unit':'°C','location':' ','name':' '},
        {'value':0.0,'unit':'°C','location':' ','name':' '},
        {'value':0.0,'unit':'°C','location':' ','name':' '},
    ]
#barometer
#radiation
#humidity
#beverage_supply
#power_consumption
#wind
#network_connections
#account_balance
#total_member_count
#people_now_present

})
#A note about this above: It will not be touched if the json document is already present or in memory.
#Reloading the config from base is a matter of forcing the data to become this value in order to assign new base elements.
#Lame, but true.
sensorlist.save()

statussensors = PlugPersist('statussensors')
statussensors.save()

currentstatus = PlugPersist('currentstatus', False)

shared_data = {}
server = None
outputthread = None

## dummy callbacks to make sure plugin gets loaded on startup
def dummycb(bot, event): pass
callbacks.add("START", dummycb)

#def apiEvents():
#    return []

def statusStr(openstatus):
    if openstatus: return 'Open' 
    else: return 'Closed'

def apiupdate(openStatus=False, who="unknown"):
    if str(currentstatus.data).lower()=='true': openStatus = True #Hackish fix!
#    api12 = {"api":"0.12","space":"NURDSpace",
#    "logo":"http://nurdspace.nl/spaceapi/logo.png",
#    "icon":{"open":"http://nurdspace.nl/spaceapi/icon-open.png",
#    "closed":"http://nurdspace.nl/spaceapi/icon-closed.png"},
#    "url":"http://nurdspace.nl/",
#    "address":"Churchillweg 68, 6706 AD Wageningen, The Netherlands",
#    "contact":{"irc":"irc://irc.oftc.net/#nurds",
#    "twitter":"@NURDspace",
#    "ml":"nurds@nurdspace.nl"},
#    "cam":["http://space.nurdspace.nl/video/channel_0.gif"],
#    "lat":51.973276,
#    "lon":5.672886,
#    "open":openStatus,
#    "lastchange":int(time.time()),
#    "sensors":apiSensors()
#    }
    api13 = {"api":"0.13","space":"NURDSpace",
    "logo":"http://nurdspace.nl/spaceapi/logo.png",
    "url":"http://nurdspace.nl/",
        "location":{
        "address":"Churchillweg 68, 6706 AD Wageningen, The Netherlands",
        "lat":51.973276,
        "lon":5.672886},
        "spacefed":{
        "spacenet":True,
        "spacesaml":False,
        "spacephone":False},
    "cam":["http://space.nurdspace.nl/video/channel_0.gif"],
    "state":{
        "open":bool(openStatus),
        "lastchange":int(time.time()),
        "trigger_person":who, #Yeah, I know. This is a FIXME
        "message":"Space is "+statusStr(currentstatus.data).upper(),
        "icon":{"open":"http://nurdspace.nl/spaceapi/icon-open.png",
        "closed":"http://nurdspace.nl/spaceapi/icon-closed.png"} },
#    "events":apiEvents(),
    "issue_report_channels":["ml"],
    "contact":{"irc":"irc://irc.oftc.net/#nurds",
        "twitter":"@NURDspace",
        "ml":"nurds@nurdspace.nl"},
    "sensors":sensorlist.data,
#    "feeds":"",
#    "projects":"",
    "cache":{"schedule":"m.02"}
    }

    try:
        with open('/mnt/spaceapi/status.json','w') as apifile:
            json.dump(api13, apifile,indent=1)
    except:
        pass

def doorsense_output(msg):
    '''The listener code for the sensor server.'''
    pswd = tcppassword.data['password']
    if msg[:len(pswd)] == pswd:
        msg = msg[len(pswd):]
        rsensor, rvalue = tuple(msg.split(':'))
        fleet = getfleet()
        for botname in fleet.list():
            bot = fleet.byname(botname)
            if bot:
                if not testing: bot.say('#nurds',rsensor+' is '+rvalue)
                bot.say('#nurdbottest',rsensor+' is '+rvalue)
        for type in sensorlist.data:
            for n, sensor in enumerate(sensorlist.data[type]):
                if rsensor.lower() == sensor['name'].lower():
                    try:
                        if type == 'door_locked': 
                            if rvalue.lower() == 'true': sensor['value']=True
                            elif rvalue.lower() == 'false': sensor['value']=False
                            else: sensor['value']=None
                        else: sensor['value']=float(rvalue)
                    except:
                        pass
                    sensorlist.data[type][n] = sensor
                    sensorlist.save()
                    apiupdate()
                    if type == 'door_locked': statuscheck()

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
    teststatus = False
    for door in sensorlist.data['door_locked']:
        if door['name'] in statussensors.data:
            if door['value'] != statussensors.data[door['name']]:
                teststatus=True
    if teststatus is not currentstatus.data:
        currentstatus.data = teststatus
        currentstatus.save()
        fleet = getfleet()
        for botname in fleet.list():
            bot = fleet.byname(botname)
            if bot:
                if not testing: bot.say('#nurds','Space status is now '+statusStr(teststatus))
                bot.say('#nurdbottest','Space status is now '+statusStr(teststatus))
        if not testing: lightset(teststatus)
        if not testing: topicset(teststatus) #was start_new_thread() but removed for threadleaking
        if not testing: mpdset(teststatus)
        if not testing: apiupdate()

def topicset(state):
    retval = None
    fleet = getfleet()
    for botname in fleet.list():
        bot = fleet.byname(botname)
        if testing: bot.say('#nurdbottest',botname)
        if bot:
            if not testing: topicdata = bot.gettopic('#nurds')
            if testing: topicdata = bot.gettopic('#nurdbottest')
#            time.sleep(5)
#            if not testing: topicdata = bot.gettopic('#nurds')
#            if testing: topicdata = bot.gettopic('#nurdbottest')
#            if testing: bot.say('#nurdbottest',str(topicdata))
#            if not topicdata and not testing: bot.say('#nurds',"can't get topic data, but the status should be toggled to "+statusStr(state)+'!') ; return
            if not topicdata: bot.say('#nurdbottest',"can't get topic data, but the status should be toggled to "+statusStr(state)+'!') ; return
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
            if not testing: bot.settopic('#nurds', newtopic)
            if testing: bot.settopic('#nurdbottest', newtopic)
    return retval

def mpdset(state):
    mpdstats = mpd('status') #list of tuples
    for x, y in mpdstats:
        if x == 'state': mpdstate = y
    if state:
        if mpdstate == 'pause': mpd('play')
    else:
        if mpdstate == 'play': mpd('pause')

def lightset(state):
    if state:
        lightprofile_activate('on')
    else:
        lightprofile_activate('off')

def handle_status(bot, ievent):
    cs = currentstatus.data
    ievent.reply('Space is currently '+statusStr(cs)+'.')
    topicset(cs)
#    mpdset(cs)
#    apiupdate(cs)
#    lightset(cs)

cmnds.add('status', handle_status, 'USER', threaded=True)
examples.add('status', 'Analyses the space status ad corrects the topic to reflect.', 'status')

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

def topiccb(bot, ievent):
    topicset(currentstatus.data)

lastcall = time.time()
def pretopiccb(bot, ievent):
    global lastcall
    if time.time()-10>lastcall:
        lastcall = time.time()
        return True
    else:
        return False

callbacks.add('PRIVMSG', topiccb, pretopiccb)
cmnds.add("doorsense-disable", handle_doorsense_disable, "OPER")
examples.add("doorsense-disable", "disable doorsense server", "doorsense-disable")


