# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect
from sqlalchemy import or_, and_, func, not_, desc
import random

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery, py_unicode
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess

# googledrive api
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

# 전역변수
service     = None
json_list   = []

#########################################################

class LogicGdrive(LogicModuleBase):
    db_default = {
        'gdrive_auth_path' : u'',
        'gdrive_auto_start' : 'False',
        'gdrive_interval' : u'60',
        'gdrive_root_folder_id' : u'',
        'gdrive_category_rules' : u'',
        'gdrive_plex_path_rule': u'/UserPMS/orial|/mnt/plex',
    }

    def __init__(self, P):
        super(LogicGdrive, self).__init__(P, 'setting')
        self.name = 'gdrive'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        P.logger.debug('sub:%s', sub)
        if sub == 'setting':
            job_id = '%s_%s' % (self.P.package_name, self.name)
            arg['scheduler'] = str(scheduler.is_include(job_id))
            arg['is_running'] = str(scheduler.is_running(job_id))
        elif sub == 'list':
            arg['categories'] = ','.join(LogicGdrive.get_categories())
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)


    def process_ajax(self, sub, req):
        try:
            ret = {'ret':'success', 'list':[]}
            P.logger.debug('GD-AJAX %s', sub)
            P.logger.debug(req)
            P.logger.debug(req.form)

            if sub == 'web_list':
                ret = ModelGdriveItem.web_list(req)
            elif sub == 'create_shortcut':
                entity_id = int(req.form['id'])
                ret = LogicGdrive.create_shortcut(entity_id)

            return jsonify(ret)

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        logger.debug('scheduler function!!!!!!!!!!!!!!')
        if app.config['config']['use_celery']:
            result = LogicGdrive.task.apply_async()
            result.get()
        else:
            LogicGdrive.task()

    #########################################################
    @staticmethod
    def initialize():
        global service, json_list

        json_path = ModelSetting.get('gdrive_auth_path')
        if not os.path.exists(json_path):
            logger.error('can not recognize gdrive_auth_path(%s)', json_path)
            data = {'type':'warning', 'msg':'인증파일(.json) 경로를 확인해주세요.'}
            socketio.emit('notify', data, namespace='/framework', broadcast=True)
            return

        if os.path.isdir(json_path):
            json_list = LogicGdrive.get_all_jsonfiles(json_path)
            logger.debug('load json list(%d)', len(json_list))
            json_file = ''.join(random.sample(json_list, 1))
        else:
            json_file = json_path
            json_list = [json_path]

        logger.debug('json_file: %s', json_file)

        scope = ['https://www.googleapis.com/auth/drive']
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)
            service = build('drive', 'v3', credentials=credentials)
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    @celery.task
    def task():
        try:
            global service, json_list

            if service == None:
                LogicGdrive.initialize()

            category_rules = LogicGdrive.get_category_rules()

            for k, v in category_rules.items():
                category = k
                agent_type, gd_folder_id, plex_folder_id = v
                folders = LogicGdrive.get_all_folders(gd_folder_id)
                for folder_id in folders:
                    r = LogicGdrive.get_folder_info(folder_id)
                    logger.debug('%s,%s,%s,%s', r['id'],r['name'],r['mimeType'],r['parent'])

                    entity = None
                    entity = ModelGdriveItem.get_by_folder_id(folder_id)
                    if entity != None and entity.parent_folder_id == r['parent']:
                        logger.debug(u'SKIP: 이미 존재하는 아이템: %s', r['name'])
                        continue


                    info = LogicGdrive.get_metadata(agent_type, r['name'])
                    if len(info) == 0:
                        logger.debug(u'메타정보 조회실패: %s:%s', agent_type, r['name'])
                        continue
                    info['category'] = category
                    info['agent_type'] = agent_type
                    info['root_folder_id'] = gd_folder_id
                    info['target_folder_id'] = plex_folder_id

                    info['name'] = r['name']
                    info['mime_type'] = r['mimeType']
                    info['folder_id'] = r['id']
                    info['parent_folder_id'] = r['parent']

                    entity = LogicGdrive.create_gd_entity(info)
                    #logger.debug(','.join([str(x) for x in info.values()]))

                    # insert to DB

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_gd_entity(info):
        try:
            entity = ModelGdriveItem(info['name'], info['folder_id'])
            if entity == None: return None
            entity.category = py_unicode(info['category'])
            entity.agent_type = py_unicode(info['agent_type'])
            entity.root_folder_id = py_unicode(info['root_folder_id'])
            entity.target_folder_id = py_unicode(info['target_folder_id'])
            entity.mime_type = py_unicode(info['mime_type'])
            entity.parent_folder_id = py_unicode(info['parent_folder_id'])
            entity.code = py_unicode(info['code'])
            entity.status = info['status']
            entity.title = py_unicode(info['title'])
            entity.site = py_unicode(info['site'])
            entity.studio = py_unicode(info['studio'])
            entity.poster_url = py_unicode(info['poster_url'])
            entity.year = info['year']
            entity.save()
            return entity
        
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def create_shortcut(db_id):
        global service
        try:
            if service == None: LogicGdrive.initialize()
            entity = ModelGdriveItem.get_by_id(db_id)
            shortcut_metadata = {
                'Name': entity.name,
                'mimeType': 'application/vnd.google-apps.shortcut',
                'shortcutDetails': {
                    'targetId': entity.folder_id
                },
                'parents': [entity.target_folder_id]
            }
            shortcut = service.files().create(body=shortcut_metadata, 
                    fields='id,shortcutDetails').execute()
            #logger.debug(json.dumps(shortcut, indent=2))

            # entity update
            entity.shortcut_created = True
            entity.shortcut_folder_id = py_unicode(shortcut['id'])
            entity.gdrive_path = LogicGdrive.get_gdrive_full_path(entity.shortcut_folder_id, entity.root_folder_id)
            entity.plex_path = LogicGdrive.get_plex_path(entity.gdrive_path)
            logger.debug('gdpath(%s),plexpath(%s)', entity.gdrive_path, entity.plex_path)
            entity.save()

            logger.debug(u'바로가기 생성완료(%s)', entity.shortcut_folder_id)
            return { 'ret':'success', 'msg':'바로가기 생성 성공{n}'.format(n=entity.name) }

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
            return { 'ret':'error', 'msg':'생성실패! 로그를 확인해주세요.' }

    @staticmethod
    def get_category_rules():
        try:
            rules = {}
            lists = ModelSetting.get_list('gdrive_category_rules', '\n')
            lists = Util.get_list_except_empty(lists)
            for line in lists:
                agent_type, category, gdriveid, plexid = line.split(',')
                logger.debug('category_rule: %s,%s,%s,%s', agent_type, category, gdriveid, plexid)
                rules[category] = [agent_type.lower(), gdriveid, plexid]
            return rules
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_categories():
        try:
            rules = {}
            lists = ModelSetting.get_list('gdrive_category_rules', '\n')
            lists = Util.get_list_except_empty(lists)
            categories = [x.split(',')[1] for x in lists]
            return categories
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())

    @staticmethod
    def get_metadata(agent_type, title):
        from metadata.logic_ktv import LogicKtv
        from metadata.logic_movie import LogicMovie
        from metadata.logic_ftv import LogicFtv

        agent_map = {'ktv':LogicKtv(LogicKtv), 'ftv':LogicFtv(LogicFtv), 
                'movie':LogicMovie(LogicMovie)}

        site_map = {'ktv':['daum','tving','wavve'],
                'ftv':['daum', 'tvdb', 'tmdb', 'watcha', 'tmdb'],
                'movie':['naver', 'daum', 'tmdb', 'watcha', 'wavve', 'tving']}

        logger.debug('agent_type: %s, title:%s', agent_type, title)
        #TV
        if agent_type != 'movie': metadata = agent_map[agent_type].search(title)
        else: #MOVIE
            import guessit
            git = guessit.guessit(title)
            title = git['title']
            year = int(git['year']) if 'year' in git else 1900
            metadata = agent_map[agent_type].search(title, year)

        #if agent_type == 'MOVIE':
            #logger.debug(json.dumps(metadata, indent=2))
        info = {}
        for site in site_map[agent_type]:
            if agent_type != 'movie': # TV
                if site in metadata:
                    r = metadata[site]
                    info['code'] = r['code']
                    info['status'] = r['status']
                    info['title'] = r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = r['studio']
                    info['year'] = r['year']
                    break
            else: # movie
                for r in metadata:
                    info['code'] = r['code']
                    info['status'] = 2
                    info['title'] = r['title']
                    info['site'] = r['site']
                    info['poster_url'] = r['image_url']
                    info['studio'] = u''
                    info['year'] = r['year']
                    break

        return info
    
    @staticmethod
    def get_all_jsonfiles(target_path):
        file_list = []

        for (path, dir, files) in os.walk(target_path):
            for filename in files:
                ext = os.path.splitext(filename)[-1]
                if ext == '.json':
                    file_list.append(os.path.join(path, filename))

        return file_list

    @staticmethod
    def get_plex_path(gdrive_path):
        try:
            rule = ModelSetting.get('gdrive_plex_path_rule')
            if rule == u'' or rule.find('|') == -1:
                return gdrive_path
            if rule is not None:
                tmp = rule.split('|')
                ret = gdrive_path.replace(tmp[0], tmp[1])

                # SJVA-PMS의 플랫폼이 다른 경우
                if tmp[0][0] != tmp[1][0]:
                    if gdrive_path[0] == '/': # Linux   -> Windows
                        ret = ret.replace('/', '\\')
                    else:                  # Windows -> Linux
                        ret = ret.replace('\\', '/')
                return ret

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_folder_info(folder_id):
        global service
        info = service.files().get(fileId=folder_id, fields='id, name, mimeType, parents').execute()
        ret = {'id':info['id'], 'mimeType':info['mimeType'], 'name':info['name'], 'parent':info['parents'][0]}
        return ret

    @staticmethod
    def get_gdrive_full_path(folder_id, root_folder_id):
        global service
        pathes = []

        parent_id = folder_id
        while True:
            r = service.files().get(fileId=parent_id, fields='id, name, mimeType, parents').execute()
            #logger.debug(json.dumps(r, indent=2))
            if r['id'] == root_folder_id:
                pathes.append(r['name'])
                break

            if 'parents' in r:
                parent_id = r['parents'][0]
                pathes.append(r['name'])
            else:
                pathes.append(r['name'])
                break

        pathes.append('')
        pathes.reverse()
        return u'/'.join(pathes)

    @staticmethod
    def get_all_folders_in_folder(root_folder_id):
        global service

        child_folders = {}
        page_token = None
        query = "mimeType='application/vnd.google-apps.folder' \
                and '{r}' in parents".format(r=root_folder_id)

        while True:
            response = service.files().list(q=query,
                    spaces='drive',
                    pageSize=1000,
                    fields='nextPageToken, files(id, name, parents, modifiedTime)',
                    pageToken=page_token).execute()
    
            folders = response.get('files', [])
            page_token = response.get('nextPageToken', None)

            for folder in folders:
                child_folders[folder['id']] = folder['parents'][0]
            if page_token is None: break
    
        return child_folders

    @staticmethod
    def get_subfolders_of_folder(folder_to_search, all_folders):
        temp_list = [k for k, v in all_folders.items() if v == folder_to_search]
        for sub_folder in temp_list:
            yield sub_folder
            for x in LogicGdrive.get_subfolders_of_folder(sub_folder, all_folders):
                yield x

    @staticmethod
    def get_all_folders(root_folder_id):
        all_folders = LogicGdrive.get_all_folders_in_folder(root_folder_id)
        target_folder_list = []
        for folder in LogicGdrive.get_subfolders_of_folder(root_folder_id, all_folders):
            target_folder_list.append(folder)
        return target_folder_list

    @staticmethod
    def get_files(target_path, target_ext_list=None, except_name_list=None):
        file_list = []

        for (path, dir, files) in os.walk(target_path):
            for filename in files:
                ext = os.path.splitext(filename)[-1]
                if target_ext_list != None:
                    if ext not in target_ext_list:
                        continue

                if except_name_list != None:
                    for except_name in except_name_list:
                        if path.find(except_name) != -1:
                            continue

                file_list.append(os.path.join(path, filename))

        return file_list


class ModelGdriveItem(db.Model):
    __tablename__ = '%s_gdrive_library_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    # basic info
    category = db.Column(db.String)   # from category_rules
    agent_type = db.Column(db.String) # ktv, ftv, movie, av?
    root_folder_id = db.Column(db.String)
    target_folder_id = db.Column(db.String)
    shortcut_created = db.Column(db.Boolean)
    shortcut_folder_id = db.Column(db.String)
    gdrive_path = db.Column(db.String)
    plex_path = db.Column(db.String)

    # info from gdrive
    name = db.Column(db.String)
    mime_type = db.Column(db.String)
    folder_id = db.Column(db.String)
    parent_folder_id = db.Column(db.String)

    # info from metadata
    code = db.Column(db.String)
    status = db.Column(db.Integer)
    title = db.Column(db.String)
    site = db.Column(db.String)
    studio = db.Column(db.String)
    poster_url = db.Column(db.String)
    year = db.Column(db.Integer)

    def __init__(self, name, folder_id):
        self.created_time = datetime.now()
        self.name = py_unicode(name)
        self.folder_id = py_unicode(folder_id)
        self.shorcut_created = False

    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        return ret
    
    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, id):
        return db.session.query(cls).filter_by(id=id).first()
    
    @classmethod
    def get_by_folder_id(cls, folder_id):
        return db.session.query(cls).filter_by(folder_id=folder_id).first()

    @classmethod
    def get_by_code(cls, code):
        return db.session.query(cls).filter_by(code=code).first()

    @classmethod
    def web_list(cls, req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            category = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            if 'category' in req.form:
                category = req.form['category']
            #option = req.form['option']
            #order = req.form['order'] if 'order' in req.form else 'desc'

            #query = cls.make_query(search=search, option=option, order=order)
            query = cls.make_query(search=search, category=category)
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            logger.debug('cls count:%s', count)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            #ModelSetting.set('jav_censored_last_list_option', '%s|%s|%s|%s' % (option, order, search, page))
            return ret
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @classmethod
    def make_query(cls, search='', category='all', option='all', order='desc'):
        query = db.session.query(cls)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.title.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                for tt in tmp:
                    if tt != '':
                        query = query.filter(cls.title.like('%'+tt.strip()+'%'))
            else:
                query = query.filter(or_(cls.title.like('%'+search+'%'), cls.name.like('%'+search+'%')))

        if category != 'all':
            query = query.filter(cls.category == category)

        #if option != 'all':
            #query = query.filter(cls.move_type.like('%'+option+'%'))

        if order == 'desc':
            query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(cls.id)

        return query 
