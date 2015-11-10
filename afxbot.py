#!/usr/bin/env python3
# coding=UTF-8

import logging
import telegram
import re
import random
import json
import sqlite3
import string
import http
from datetime import date, datetime, timedelta
from pathlib import Path
import hashlib

LAST_UPDATE_ID = None

logger = logging.getLogger()

config = None

fortune_strs = ['大凶', '凶', '平', '小吉', '大吉']

motd_date = None
motd_msg = None

resp_db = None
kw_list = None
kw_list_m = None
kw_list_get = None
symptom_tbl = None
symptom_get = None

unified_kw_list = None
unified_get_list = None

is_running = True
is_accepting_photos = False

wash_record = dict()

class WashSnake:
    def __init__(self, firsttime, content, **kwargs):
        self.firsttime = firsttime
        self.content = content
        
        self.responded = False
        self.repeattimes = kwargs.get('repeattimes')
        if self.repeattimes == None:
            self.repeattimes = 0
            

def getLatestUpdateId(bot):
    global LAST_UPDATE_ID
    try:
        LAST_UPDATE_ID = bot.getUpdates()[-1].update_id
        LAST_UPDATE_ID = bot.getUpdates(offset=LAST_UPDATE_ID)[-1].update_id
    except IndexError:
        LAST_UPDATE_ID = None

def main():
    global LAST_UPDATE_ID, motd_date, motd_msg, logger, resp_db
    global config
    logging.basicConfig(filename='/var/www/__priv/afxbot.log', level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger = logging.getLogger('AFX_bot')
    logger.setLevel(logging.DEBUG)

    # initialization
    try:
        f = open('config.json', 'r')
        config = json.loads(f.read())

        # check configurations
        if(config['bot_token'] == None
            or config['resp_db'] == None
            or config['adm_ids'] == None
            or config['limited_chats'] == None):
            raise ValueError

        f.close()
        
        initResp()
    except FileNotFoundError:
        logger.error('config file not found!')
        raise
    except ValueError:
        logger.error('config read error!')
        raise
    except:
        raise

    # Telegram Bot Authorization Token
    bot = telegram.Bot(config['bot_token'])

    try:
        f = open('motd.json', 'r')
        motd_json = json.loads(f.read())
        motd_date = datetime.strptime(motd_json['date'], '%Y-%m-%d').date()
        if (motd_date != date.today()):
            logger.info('MOTD Date mismatch')
        else:
            logger.info('MOTD Date OK')

        motd_msg = motd_json['content']
        logger.info('MOTD: \n'+motd_msg)
        f.close()
    except FileNotFoundError:
        logger.error('MOTD file not found!')
    except ValueError:
        logger.error('MOTD read error!')
        motd_date = None
        motd_msg = None
    except:
        raise

    getLatestUpdateId(bot)

    while True:
        # This will be our global variable to keep the latest update_id when requesting
        # for updates. It starts with the latest update_id if available.
        try:
            getMesg(bot)
        except KeyboardInterrupt:
            exit()
        except http.client.RemoteDisconnected:
            logging.exception('!!! EXCEPTION HAS OCCURRED !!!')
            
            # try to reinit...
            bot = telegram.Bot(config['bot_token'])
            getLatestUpdateId(bot)
        except Exception as ex:
            logging.exception('!!! EXCEPTION HAS OCCURRED !!!')
            getLatestUpdateId(bot)

def initResp():
    global config
    global logger, resp_db
    global kw_list, kw_list_m, kw_list_get, symptom_tbl, symptom_get, unified_kw_list, unified_get_list
    try:
        resp_db = sqlite3.connect(config['resp_db'])
        resp_db.row_factory = sqlite3.Row
        c = resp_db.cursor()

        kw_list = list()
        c.execute('SELECT keyword FROM resp GROUP BY keyword ORDER BY RANDOM() DESC;')
        for kw in c:
            kw_list.append(kw['keyword'])

        kw_list_m = list()
        c.execute('SELECT keyword FROM resp_m GROUP BY keyword ORDER BY RANDOM() DESC;')
        for kw in c:
            kw_list_m.append(kw['keyword'])

        kw_list_get = list()
        c.execute('SELECT keyword FROM resp_get GROUP BY keyword ORDER BY RANDOM() DESC;')
        for kw in c:
            kw_list_get.append(kw['keyword'])

        symptom_tbl = dict()
        c.execute('SELECT before, after FROM symptom ORDER BY LENGTH(before) DESC;')
        for syms in c:
            symptom_tbl[syms['before']] = syms['after']

        symptom_get = dict()
        c.execute('SELECT before, after FROM symptom_get ORDER BY LENGTH(before) DESC;')
        for syms in c:
            symptom_get[syms['before']] = syms['after']
            
            
        unified_kw_list = kw_list + list(symptom_tbl.keys())
        unified_get_list = kw_list_get + list(symptom_get.keys())

        #logger.debug("kw_list: " + str(kw_list))
        #logger.debug("kw_list_m: " + str(kw_list_m))
        #logger.debug("kw_list_get: " + str(kw_list_get))
    except:
        raise



def getMesg(bot):
    global LAST_UPDATE_ID, logger, is_running, is_accepting_photos, wash_record


    # Request updates after the last updated_id
    for update in bot.getUpdates(offset=LAST_UPDATE_ID, timeout=10):
        # chat_id is required to reply any message
        chat_id = update.message.chat_id
        message = update.message.text
        #.encode('utf-8')

        if (message):
            if(not doAuthWithGroups(update.message.chat.id)):
                logger.debug('Access denied from: ' + str(update.message.chat.id))
                LAST_UPDATE_ID = update.update_id + 1
                continue
                
            washsnake_content = message.lower().strip()
            if(not update.message.from_user.id in wash_record.keys()):
                logger.debug('new washsnake content for ' + str(update.message.from_user.id))
                wash_record[update.message.from_user.id] = WashSnake(update.message.date, washsnake_content)
            else:
                # check
                washsnake_entry = wash_record[update.message.from_user.id];
                if(washsnake_entry.content == washsnake_content):
                    # same content, check time
                    time_delta = washsnake_entry.firsttime - update.message.date
                    if(time_delta < timedelta(seconds=60)):
                        logger.debug('wash ++ for ' + str(update.message))
                        wash_record[update.message.from_user.id].repeattimes += 1;
                        if(washsnake_entry.repeattimes >= 2):
                            if(not washsnake_entry.responded):
                                # WASH SNAKE!!
                                bot.sendMessage(chat_id = chat_id, text = '幹你娘洗蛇', reply_to_message_id = update.message.message_id)
                                wash_record[update.message.from_user.id].responded = True
                                
                            LAST_UPDATE_ID = update.update_id + 1
                            continue
                    else:
                        wash_record[update.message.from_user.id].responded = False
                        wash_record[update.message.from_user.id].firsttime = update.message.date
                else:
                    logger.debug('update wash for ' + str(update.message.from_user.id))
                    wash_record[update.message.from_user.id] = WashSnake(update.message.date, washsnake_content)

            if ('憨包在嗎' in message):
                if(is_running):
                    bot.sendMessage(chat_id = chat_id, text = '憨包狀態：正常憨包中', reply_to_message_id = update.message.message_id)
                else:
                    bot.sendMessage(chat_id = chat_id, text = '憨包狀態：不在…', reply_to_message_id = update.message.message_id)

            elif (not is_running and message.startswith('憨包回來') and doAuth(update.message.from_user.id)):
                bot.sendMessage(chat_id = chat_id, text = '（滾動）（滾回來）（？）', reply_to_message_id = update.message.message_id)
                initResp()
                is_running = True

            # 今日重點是必要的
            elif (message.startswith('/motd') or '本日重點' in message or '今日重點' in message or '今天重點' in message):
                doHandleCmd(bot, chat_id, message, update.message.from_user.username ,update.message.message_id)

            elif (is_running):
                if (message.startswith('照片GOGO') and doAuth(update.message.from_user.id)):
                    p = Path('images')
                    fl = list(p.glob('*.jpg'))
                    if(len(fl) == 0):
                        bot.sendMessage(chat_id = chat_id, text = '/images/裡頭，沒圖沒真相...', reply_to_message_id = update.message.message_id)
                    else:
                        for image_name in fl:
                            # for uploading new photos
                            nn = open(str(image_name), 'rb')
                            photo_res = bot.sendPhoto(chat_id = chat_id, photo = nn)
                            nn.close()
                            photo_mesg = photo_res.photo[-1].file_id
                            bot.sendMessage(chat_id = chat_id, text = photo_mesg, reply_to_message_id = photo_res.message_id)

                elif (message.startswith('憨包滾一圈')):
                    if(doAuth(update.message.from_user.id)):
                        initResp()
                        bot.sendMessage(chat_id = chat_id, text = '（滾動）（滾一圈後回來）（？）', reply_to_message_id = update.message.message_id)
                    else:
                        bot.sendMessage(chat_id = chat_id, text = '……（憨）', reply_to_message_id = update.message.message_id)

                elif (message.startswith('憨包滾')):
                    if(doAuth(update.message.from_user.id)):
                        bot.sendMessage(chat_id = chat_id, text = '（滾動）（滾遠遠）（？）', reply_to_message_id = update.message.message_id)
                        is_running = False
                    else:
                        bot.sendMessage(chat_id = chat_id, text = '……（憨）', reply_to_message_id = update.message.message_id)

                elif (message.startswith('憨包來吃圖')):
                    if(doAuth(update.message.from_user.id)):
                        bot.sendMessage(chat_id = chat_id, text = '（張嘴）', reply_to_message_id = update.message.message_id)
                        is_accepting_photos = True
                    else:
                        bot.sendMessage(chat_id = chat_id, text = '……（憨）', reply_to_message_id = update.message.message_id)

                elif (message.startswith('憨包吃飽沒')):
                    if(doAuth(update.message.from_user.id)):
                        bot.sendMessage(chat_id = chat_id, text = '（憨樣）', reply_to_message_id = update.message.message_id)
                        is_accepting_photos = False
                    else:
                        bot.sendMessage(chat_id = chat_id, text = '吃飽了（憨）', reply_to_message_id = update.message.message_id)

                elif (message.startswith('/adm') and doAuth(update.message.from_user.id)):
                    doHandleAdmCmd(bot, chat_id, message, update.message.message_id)

                elif (message.startswith('/')):
                    doHandleCmd(bot, chat_id, message, update.message.from_user.username ,update.message.message_id)

                elif ('今日運勢' in message):
                    doHandleFortuneTell(bot, chat_id, update.message.from_user.id ,update.message.message_id, '今日')

                elif ('明日運勢' in message):
                    doHandleFortuneTell(bot, chat_id, update.message.from_user.id ,update.message.message_id, '明日')

                elif ('昨日運勢' in message):
                    doHandleFortuneTell(bot, chat_id, update.message.from_user.id ,update.message.message_id, '昨日')

                else:
                    #logger.debug('GoHandleContent: ' + str(update.message));
                    # Reply the message
                    doHandleResponse(bot, chat_id, message, update.message.from_user.username ,update.message.message_id, update.message.from_user.id)
            else:
                logger.debug('Not running...')
        elif (update.message.photo != None and is_accepting_photos and doAuth(update.message.from_user.id)):
            try:
                logger.debug('PhotoContent: ' + update.message.photo[-1].file_id);
                photo_mesg = update.message.photo[-1].file_id
                photo_res = bot.sendPhoto(chat_id = chat_id, photo = photo_mesg)
                photo_mesg = photo_res.photo[-1].file_id
                bot.sendMessage(chat_id = chat_id, text = photo_mesg, reply_to_message_id = photo_res.message_id)
            except:
                nothing_todo = 1

        #else:
        #    logger.debug('NotHandleContent: ' + str(update.message));

        # Updates global offset to get the new updates
        LAST_UPDATE_ID = update.update_id + 1

def doAuth(id):
    return id in config['adm_ids']

def doAuthWithGroups(cid):
    return cid in config['limited_chats'] or cid in config['adm_ids']

def appendMoreSmile(str, rl = 1, ru = 3):
    return str + '\U0001F603' * random.randint(rl, ru)

def doHandleAdmCmd(bot, chat_id, mesg, mesg_id):
    global logger
    global resp_db, kw_list, kw_list_get, kw_list_m, is_accepting_photos
    global unified_kw_list, unified_get_list
    
    cmd_toks = [x.strip() for x in mesg.split(' ')]
    cmd_entity = cmd_toks[1].lower()

    c = resp_db.cursor()
    logger.debug('cmd_entity: ' + cmd_entity)

    if(cmd_entity == 'begin_img'):
        is_accepting_photos = True

    if(cmd_entity == 'end_img'):
        is_accepting_photos = False

    elif(cmd_entity == 'assign_img'):
        img_id = cmd_toks[2]
        img_kw = cmd_toks[3].lower()
        if (len(cmd_toks) > 4):
            img_tag = cmd_toks[4]
        else:
            img_tag = None
        try:
            photo_res = bot.sendPhoto(chat_id = chat_id, reply_to_message_id = mesg_id, photo = cmd_toks[2]);
            bot.sendMessage(chat_id = chat_id, text = img_kw + ' => ' + img_id , reply_to_message_id = photo_res.message_id)

            c.execute('''INSERT INTO resp_get (keyword, cont, tag) VALUES (?, ?, ?) ''', ( img_kw, img_id, img_tag, ))
            resp_db.commit()
            initResp()
        except TelegramError:
            bot.sendMessage(chat_id = chat_id, text = 'ERROR ON : ' + img_kw + ' => ' + img_id , reply_to_message_id = photo_res.message_id)
            pass

    elif(cmd_entity == 'list_get'):
        if(len(cmd_toks) > 2):
            outmesg = ''
            img_kw = cmd_toks[2].lower()

            c.execute('''SELECT cont, tag FROM resp_get WHERE keyword = ? ORDER BY IIDX DESC;''', (img_kw, ))
            for conts in c:
                if conts['tag'] == None :
                    outmesg += conts['cont'] + ' (N/A)\n'
                else:
                    outmesg += conts['cont'] + ' (' + conts['tag'] + ')\n'

            bot.sendMessage(chat_id = chat_id, text = img_kw + ' => \n' + outmesg , reply_to_message_id = mesg_id)

        else:
            outmesg = 'Supported /get keywords:\n'
            s_keys = symptom_get.keys()
            for kw in unified_get_list:
                
                if (kw in s_keys):
                    outmesg = outmesg + kw + ' -> ' + symptom_get[kw] + '\n'
                else:
                    outmesg = outmesg + kw + '\n'

            bot.sendMessage(chat_id = chat_id, text = outmesg , reply_to_message_id = mesg_id)    
            
    elif(cmd_entity == 'add_kw'):
        a=1

    elif(cmd_entity == 'list_kw'):
        s_keys = symptom_tbl.keys()
        if(len(cmd_toks) > 2):
            outmesg = ''
            if (not kw in s_keys):
                kw = cmd_toks[2].lower()

            c.execute('''SELECT cont FROM resp WHERE keyword = ? ORDER BY IIDX DESC;''', (kw, ))
            for conts in c:
                outmesg += conts['cont'] + '\n'
                

            bot.sendMessage(chat_id = chat_id, text = kw + ' => \n' + outmesg , reply_to_message_id = mesg_id)

        else:
            outmesg = 'Supported keywords:\n'
            for kw in unified_kw_list:
                
                if (kw in s_keys):
                    outmesg = outmesg + kw + ' -> ' + symptom_tbl[kw] + '\n'
                else:
                    outmesg = outmesg + kw + '\n'

            bot.sendMessage(chat_id = chat_id, text = outmesg , reply_to_message_id = mesg_id) 
            
    else:
        bot.sendMessage(chat_id = chat_id, text = 'adm what? owo'  , reply_to_message_id = mesg_id)

def doHandleCmd(bot, chat_id, mesg, username, mesg_id):
    global logger
    global resp_db, kw_list, kw_list_get, kw_list_m
    global unified_kw_list
    mesg_low = mesg.lower().replace('@afx_bot', '')

    if (mesg_low.startswith('/get ')):
        keyword = mesg_low[5:].strip()
        logger.debug('keyword: ' + keyword)

        if (keyword in symptom_get.keys()):
            keyword = symptom_get[keyword]

        if (keyword in kw_list_get):
            c = resp_db.cursor()
            c.execute('''SELECT cont FROM resp_get WHERE keyword = ? ORDER BY RANDOM() LIMIT 1;''', ( keyword, ))
            x = c.fetchone()
            bot.sendPhoto(chat_id = chat_id, reply_to_message_id = mesg_id, photo = str(x['cont']));
        else:
            bot.sendMessage(chat_id = chat_id, text = appendMoreSmile('You get nothing! '), reply_to_message_id = mesg_id)

        return True

    elif (mesg == '/roll@AFX_bot'):
        bot.sendMessage(chat_id = chat_id, text = "/roll [ 最大值 (1000) | 最小值-最大值 (20-30) | 骰數d骰面[+-調整值] (2d6, 1d20+12) | 骰數d骰面s成功值 (2d6s4) ]", reply_to_message_id = mesg_id)
        return True

    elif (mesg_low.startswith('/roll ') or mesg_low == '/roll'):
        return doHandleRoll(bot, chat_id, mesg_low, username, mesg_id)

    elif (mesg_low.startswith('/motd') or '本日重點' in mesg or '今日重點' in mesg or '今天重點' in mesg):
        return doHandleMotd(bot, chat_id, mesg, mesg_id)

    return False

def doHandleResponse(bot, chat_id, mesg, username, mesg_id, user_id):
    global resp_db
    global logger, symptom_tbl, kw_list_m
    global unified_kw_list
    mesg_low = mesg.lower()

    # hardcoded...
    if ( 'ass' in mesg_low and not 'pass' in mesg_low):
        bot.sendMessage(chat_id = chat_id, text = 'Ood', reply_to_message_id = mesg_id)
        return True

    if ('阿倫' in mesg):
        bot.sendMessage(chat_id = chat_id, text = appendMoreSmile('你需要更多的ㄅㄊ '), reply_to_message_id = mesg_id)
        return True

    """
    if user_id == 47615404:
        # convert kw
        for kw in symptom_tbl.keys():
            if kw in mesg_low:
                unified_kw = symptom_tbl[kw]
                logger.debug('keyword: ' + kw + ' -> ' + unified_kw)

                c = resp_db.cursor()
                if (unified_kw in kw_list_m):
                    c.execute('''SELECT cont FROM resp_m WHERE keyword = ? ORDER BY RANDOM() LIMIT 1;''', ( unified_kw, ))
                else:
                    c.execute('''SELECT cont FROM resp WHERE keyword = ? ORDER BY RANDOM() LIMIT 1;''', ( unified_kw, ))

                x = c.fetchone()
                bot.sendMessage(chat_id = chat_id, text = str(x['cont']), reply_to_message_id = mesg_id)
                return True

        # find other kw's
        for kw in kw_list_m:
            if kw in mesg_low:
                logger.debug('keyword: ' + kw )

                c = resp_db.cursor()
                c.execute('''SELECT cont FROM resp_m WHERE keyword = ? ORDER BY RANDOM() LIMIT 1;''', ( kw, ))
                x = c.fetchone()
                bot.sendMessage(chat_id = chat_id, text = str(x['cont']), reply_to_message_id = mesg_id)
                return True

    else:
    """
    random.shuffle(unified_kw_list)
    s_keys = symptom_tbl.keys()

    # convert kw
    for kw in unified_kw_list:
        if kw in mesg_low:
            if (kw in s_keys):
                unified_kw = symptom_tbl[kw]
                logger.debug('keyword: ' + kw + ' -> ' + unified_kw)
            else:
                unified_kw = kw
                logger.debug('keyword: ' + kw )

            c = resp_db.cursor()
            c.execute('''SELECT cont FROM resp WHERE keyword = ? ORDER BY RANDOM() LIMIT 1;''', ( unified_kw, ))
            x = c.fetchone()
            bot.sendMessage(chat_id = chat_id, text = str(x['cont']), reply_to_message_id = mesg_id)
            return True

    return False

def doHandleRoll(bot, chat_id, mesg_low, username, mesg_id):
    if (mesg_low == '/roll'):
        d_cmd = ''
    else:
        d_cmd = mesg_low[6:].strip()

    res = re.match('([0-9]+)d([0-9]+)s([0-9]+)', d_cmd)
    if (res):
        dn = int(res.group(1))
        dt = int(res.group(2))
        ds = int(res.group(3))
        dstr = '('
        succ = 0

        if(dn > 100): dn = 100

        for i in range(dn):
            val = random.randint(1, dt)
            if (val >= ds): succ += 1
            dstr += str(val) + ', '

        dstr = '{0}d{1}s{2} : {3}) >= {2}, 成功 {4} 次'.format(dn, dt, ds, dstr[:-2], succ);
        bot.sendMessage(chat_id = chat_id, text = dstr, reply_to_message_id = mesg_id)
        return True

    res = re.match('([0-9]+)d([0-9]+)([+-][0-9]+)?', d_cmd)
    if (res):
        dn = int(res.group(1))
        dt = int(res.group(2))
        if (res.group(3) != None) :
            dm = int(res.group(3))
        else:
            dm =  0;

        dstr = '('
        sum = 0

        if(dn > 100): dn = 100

        for i in range(dn):
            val = random.randint(1, dt)
            sum += val
            dstr += str(val) + ', '

        if (dm == 0):
            dstr = '{0}d{1} : {2}) = {3}'.format(dn, dt, dstr[:-2], sum);
        else:
            if (dm > 0):
                dm_str = '+' + str(dm)
            else:
                dm_str = str(dm)
            dstr = '{0}d{1}{2} : {3}) {2} = {4} {2} = {5}'.format(dn, dt, dm_str, dstr[:-2], sum, sum+dm);
        bot.sendMessage(chat_id = chat_id, text = dstr, reply_to_message_id = mesg_id)
        return True

    res = re.match('([0-9]+)(-([0-9]+))?', d_cmd)
    if (res):
        if (res.group(3) != None):
            dl = int(res.group(1))
            du = int(res.group(3))
        else:
            dl = 1
            du = int(res.group(1))

        dstr = '你擲出了: {0} ({1}-{2})'.format(random.randint(dl, du), dl, du);
        bot.sendMessage(chat_id = chat_id, text = dstr, reply_to_message_id = mesg_id)
        return True

    if (d_cmd == ''):
        dstr = '你擲出了: {0} (1-100)'.format(random.randint(1,100));
        bot.sendMessage(chat_id = chat_id, text = dstr, reply_to_message_id = mesg_id)
        return True

    else:
        bot.sendMessage(chat_id = chat_id, text = "/roll [ 最大值 (1000) | 最小值-最大值 (20-30) | 骰數d骰面[+-調整值] (2d6, 1d20+12) | 骰數d骰面s成功值 (2d6s4) ]", reply_to_message_id = mesg_id)
        return True

def doHandleFortuneTell(bot, chat_id, target_id, message_id, type):
    global fortune_strs
    md5 = hashlib.md5()

    format_str = '^_^ANFAUGLIR_SALT##$$%Y__??__%m__!!__%d**&&ANFAUGLIR_SALT^_^'
    
    fortune_date = date.today()
    if(type == '明日'):
        fortune_date = fortune_date+timedelta(days=1)
    elif (type == '昨日'):
        fortune_date = fortune_date-timedelta(days=1)
    
    f_data = bytearray(str(target_id) + datetime.strftime(fortune_date, format_str), 'utf-8')

    md5.update(f_data)
    fstr = type + '運勢：' + fortune_strs[int(md5.digest()[12]) % len(fortune_strs)]
    bot.sendMessage(chat_id = chat_id, text = fstr, reply_to_message_id = message_id)



def doHandleMotd(bot, chat_id, mesg, mesg_id):
    global motd_date, motd_msg
    mesg_low = mesg.lower().replace('@afx_bot', '')
    mesg = mesg.replace('@afx_bot', '')

    if(mesg_low.startswith('/motd')):
        if(mesg_low == '/motd'):  # print motd
            printMotd(bot, chat_id, mesg_id)
        else:
            motd_cmd = mesg[5:].strip()
            motd_msg = motd_cmd
            motd_date = date.today()
            today_str = datetime.strftime(motd_date, '%Y-%m-%d')
            logger.info('MOTD: \n'+motd_msg)

            try:
                f = open('motd.json', 'w')
                logger.info('writing MOTD contents')
                f.write(json.dumps({'date' : today_str, 'content' : motd_msg}))
                f.close()
            except Exception as ex:
                logging.exception('!!! EXCEPTION HAS OCCURRED !!!')
                pass

            bot.sendMessage(chat_id = chat_id, text = today_str + ' 今日重點已更新：\n' + motd_msg, reply_to_message_id = mesg_id)
    elif (mesg_low == '/motd' or '本日重點' in mesg_low or '今日重點' in mesg_low or '今天重點' in mesg_low):
        printMotd(bot, chat_id, mesg_id)
    else:
        logging.debug('wtf?!')

def printMotd(bot, chat_id, mesg_id):
    global motd_date, motd_msg

    if (motd_date != None):
        motd_date_str = datetime.strftime(motd_date, '%Y-%m-%d')
    else:
        motd_date_str = '????-??-??'

    if (motd_date == None):
        bot.sendMessage(chat_id = chat_id, text = '今天還沒有重點', reply_to_message_id = mesg_id)
    if (motd_date != date.today()):
        bot.sendMessage(chat_id = chat_id, text = '今天還沒有重點\n' +
                                                  motd_date_str + ' 重點複習：\n' + motd_msg, reply_to_message_id = mesg_id)
    else:
        bot.sendMessage(chat_id = chat_id, text = motd_date_str + ' 今日重點：\n' + motd_msg, reply_to_message_id = mesg_id)

if __name__ == '__main__':
    main()