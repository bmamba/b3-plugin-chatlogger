#
# ChatLogger Plugin for BigBrotherBot
# Copyright (C) 2008 Courgette
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
# Changelog:
#
# 28/07/2008 - 0.0.1
# - manage say, teamsay and privatesay messages
# 14/08/2008 - 0.1.0
# - fix security issue with player names of messages containing double quote or antislash characters (Thx to Anubis for report and tests)
# - allows to setup a daily purge of old messages to keep your database size reasonable
# 13/09/2008 - 0.1.1
# - in config, the hour defined for the purge is now understood in the timezone defined in the main B3 config file (before, was understood as UTC time)
# - fix mistake in log text
# 7/11/2008 - 0.1.2 - xlr8or
# - added missing 'import b3.timezones'
# 22/12/2008 - 0.2.0 - Courgette
# - allow to use a customized table name for storing the
#   log to database. Usefull if multiple instances of the
#   bot share the same database.
#   Thanks to Eire.32 for bringing up the idea and testing.

__version__ = '0.2.0'
__author__  = 'Courgette'

import b3, time, threading, re
from b3 import clients
import b3.events
import b3.plugin
import b3.cron
import b3.timezones
import datetime, string
from b3 import functions

#--------------------------------------------------------------------------------------------------
class ChatloggerPlugin(b3.plugin.Plugin):
  _cronTab = None
  _max_age_in_days = None
  _hours = None
  _minutes = None
  _db_table = None
  
  
  def onLoadConfig(self):
    # remove eventual existing crontab
    if self._cronTab:
      self.console.cron - self._cronTab

    try:
      self._db_table = self.config.get('database', 'db_table')
      self.debug('Using table (%s) to store log', self._db_table)
    except:
      self._db_table = 'chatlog'
      self.debug('Using default value (%s) for db_table', self._db_table) 
      
    try:
      max_age = self.config.get('purge', 'max_age')
    except:
      days = 0
      self.debug('Using default value (%s) for max_age', days)
      
    # convert max age string to days. (max age can be written as : 2d for 'two days', etc)
    try:
      if max_age[-1:] == 'd':
        days = int(max_age[:-1])
      elif max_age[-1:] == 'w':
        days = int(max_age[:-1]) * 7
      elif max_age[-1:] == 'm':
        days = int(max_age[:-1]) * 30
      elif max_age[-1:] == 'y':
        days = int(max_age[:-1]) * 365
      else:
        days = int(max_age)
    except ValueError:
      self.error("Could not convert %s to a valid number of days."%max_age)
      days = 0
    
    self.debug('max age : %s => %s days'%(max_age, days))
    
    # force max age to be at least one day
    if days != 0 and days < 1:
      self._max_age_in_days = 1
    else:
      self._max_age_in_days = days

    
    try:
      self._hours = self.config.getint('purge', 'hour')
      if self._hours < 0:
        self._hours = 0
      elif self._hours > 23:
        self._hours = 23
    except:
      self._hours = 0
      self.debug('Using default value (%s) for hours', self._hours)
      
    try:
      self._minutes = self.config.getint('purge', 'min')
      if self._minutes < 0:
        self._minutes = 0
      elif self._minutes > 59:
        self._minutes = 59
    except:
      self._minutes = 0
      self.debug('Using default value (%s) for minutes', self._minutes)
    
    if self._max_age_in_days != 0:
      # Get time_zone from main B3 config
      tzName = self.console.config.get('b3', 'time_zone').upper()
      tzOffest = b3.timezones.timezones[tzName]
      hoursGMT = (self._hours - tzOffest)%24
      self.debug("%02d:%02d %s => %02d:%02d UTC" % (self._hours, self._minutes, tzName, hoursGMT, self._minutes))
      self.info('everyday at %2d:%2d %s, chat messages older than %s days will be deleted'%(self._hours, self._minutes, tzName, self._max_age_in_days))
      self._cronTab = b3.cron.PluginCronTab(self, self.purge, 0, self._minutes, hoursGMT, '*', '*', '*')
      self.console.cron + self._cronTab
    else:
      self.info("chat log messages are kept forever")
  
  def startup(self):
    """\
    Initialize plugin settings
    """
    
    # listen for client events
    self.registerEvent(b3.events.EVT_CLIENT_SAY)
    self.registerEvent(b3.events.EVT_CLIENT_TEAM_SAY)
    self.registerEvent(b3.events.EVT_CLIENT_PRIVATE_SAY)


    

  def onEvent(self, event):
    """\
    Handle intercepted events
    """
    if not event.client or event.client.cid == None or len(event.data) <= 0:
      return
    
    if event.type == b3.events.EVT_CLIENT_SAY:
      chat = ChatData(self, event)
      chat._table = self._db_table
      chat.save()
    if event.type == b3.events.EVT_CLIENT_TEAM_SAY:
      chat = TeamChatData(self, event)
      chat._table = self._db_table
      chat.save()
    if event.type == b3.events.EVT_CLIENT_PRIVATE_SAY:
      chat = PrivateChatData(self, event)
      chat._table = self._db_table
      chat.save()
 
  def purge(self):
    if not self._max_age_in_days or self._max_age_in_days == 0:
      self.warning('max_age is invalid [%s]'%self._max_age_in_days)
      return False
      
    self.info('purge of chat messages older than %s days ...'%self._max_age_in_days)
    q = "DELETE FROM %s WHERE msg_time < %i"%(self._db_table, self.console.time() - (self._max_age_in_days*24*60*60)) 
    self.debug(q)
    cursor = self.console.storage.query(q)
    #self.debug('cursor : %s'%cursor)
    
    
class ChatData(object):
  #default name of the table for this data object
  _table = 'chatlog'
  plugin = None
  
  #fields of the table
  msg_type = 'ALL' # ALL, TEAM or PM
  client_id = None
  client_name = None
  client_team = None
  msg = None
  
  def __init__(self, plugin, event):
    self.plugin = plugin
    self.client_id = event.client.id
    self.client_name = event.client.name
    self.client_team = event.client.team
    self.msg = event.data
    
  def _insertquery(self):
    return "INSERT INTO %s (msg_time, msg_type, client_id, client_name, client_team, msg) VALUES (%s, \"%s\", %s, \"%s\", %s, \"%s\")" % (self._table, self.plugin.console.time(), self.msg_type, self.client_id, self.client_name.replace('\\','\\\\').replace('"','\\"'), self.client_team, self.msg.replace('\\','\\\\').replace('"','\\"'))

  def save(self):
    self.plugin.debug("%s, %s, %s, %s"% (self.msg_type, self.client_id, self.client_name, self.msg))
    
    q = self._insertquery()
    self.plugin.debug("query: %s" % q)
    
    cursor = self.plugin.console.storage.query(q)
    if (cursor.rowcount > 0):
      self.plugin.debug("rowcount: %s, id:%s" % (cursor.rowcount, cursor.lastrowid))
    else:
      self.plugin.warn("inserting chat failed")
      
      
    
class TeamChatData(ChatData):
  msg_type = 'TEAM'
  
  def __init__(self, plugin, event):
    ChatData.__init__(self, plugin, event)
  
  
  
  
class PrivateChatData(ChatData):
  msg_type = 'PM'
  
  target_id = None
  target_name = None
  target_team = None
  
  def __init__(self, plugin, event):
    ChatData.__init__(self, plugin, event)
    self.target_id = event.target.id
    self.target_name = event.target.name
    self.target_team = event.target.team
    
  def _insertquery(self):
    return "INSERT INTO %s (msg_time, msg_type, client_id, client_name, client_team, msg, target_id, target_name, target_team) VALUES (%s, \"%s\", %s, \"%s\", %s, \"%s\", %s, \"%s\", %s)" % (self._table, self.plugin.console.time(), self.msg_type, self.client_id, self.client_name.replace('\\','\\\\').replace('"','\\"'), self.client_team, self.msg.replace('\\','\\\\').replace('"','\\"'), self.target_id, self.target_name.replace('\\','\\\\').replace('"','\\"'), self.target_team)
  