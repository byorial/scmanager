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

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicGdrive(LogicModuleBase):
    db_default = {
        'gdrive_auth_path' : '',
        'gdrive_scheduler_interval' : '',
    }

    def __init__(self, P):
        super(LogicGdrive, self).__init__(P, 'setting')
        self.name = 'gdrive'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        if sub == 'setting':
            job_id = '%s_%s' % (self.P.package_name, self.name)
            arg['scheduler'] = str(scheduler.is_include(job_id))
            arg['is_running'] = str(scheduler.is_running(job_id))
        return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)


    def process_ajax(self, sub, req):
        try:
            return jsonify({'ret':'success', 'data':newfilename})

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        if app.config['config']['use_celery']:
            result = LogicGdrive.task.apply_async()
            result.get()
        else:
            LogicGdrive.task()

    #########################################################

    @staticmethod
    @celery.task
    def task():
        while True:
            try:
                logger.debug('main routine')
                time.sleep(60)

            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())


"""
class ModelJavcensoredItem(db.Model):
    __tablename__ = '%s_jav_censored_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    reserved = db.Column(db.JSON)

    is_file = db.Column(db.Boolean)
    source_dir = db.Column(db.String)
    source_filename = db.Column(db.String)
    source_path = db.Column(db.String)
    move_type = db.Column(db.String) # -1, 0:정상, 1:타입불일치, 2:중복삭제 
    target_dir = db.Column(db.String)
    target_filename = db.Column(db.String)
    target_path = db.Column(db.String)
    log = db.Column(db.String)

    meta_result = db.Column(db.String)
    poster = db.Column(db.String)


    def __init__(self, source_dir, source_filename):
        self.created_time = datetime.now()
        self.is_file = True
        self.source_dir = source_dir
        self.source_filename = source_filename
        self.move_type = None

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
    def web_list(cls, req):
        try:
            ret = {}
            page = 1
            page_size = 30
            job_id = ''
            search = ''
            if 'page' in req.form:
                page = int(req.form['page'])
            if 'search_word' in req.form:
                search = req.form['search_word']
            option = req.form['option']
            order = req.form['order'] if 'order' in req.form else 'desc'

            query = cls.make_query(search=search, option=option, order=order)
            count = query.count()
            query = query.limit(page_size).offset((page-1)*page_size)
            logger.debug('cls count:%s', count)
            lists = query.all()
            ret['list'] = [item.as_dict() for item in lists]
            ret['paging'] = Util.get_paging_info(count, page, page_size)
            ModelSetting.set('jav_censored_last_list_option', '%s|%s|%s|%s' % (option, order, search, page))
            return ret
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @classmethod
    def make_query(cls, search='', option='all', order='desc'):
        query = db.session.query(cls)
        if search is not None and search != '':
            if search.find('|') != -1:
                tmp = search.split('|')
                conditions = []
                for tt in tmp:
                    if tt != '':
                        conditions.append(cls.source_filename.like('%'+tt.strip()+'%') )
                query = query.filter(or_(*conditions))
            elif search.find(',') != -1:
                tmp = search.split(',')
                for tt in tmp:
                    if tt != '':
                        query = query.filter(cls.source_filename.like('%'+tt.strip()+'%'))
            else:
                query = query.filter(or_(cls.source_filename.like('%'+search+'%'), cls.target_filename.like('%'+search+'%')))

        #if av_type != 'all':
        #    query = query.filter(cls.av_type == av_type)

        if option != 'all':
            query = query.filter(cls.move_type.like('%'+option+'%'))

        if order == 'desc':
            query = query.order_by(desc(cls.id))
        else:
            query = query.order_by(cls.id)

        return query 

"""
