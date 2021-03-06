#coding=utf-8
import scrapy
from scrapy.selector import Selector
from scrapy.contrib.spiders import CrawlSpider,Rule
from scrapy.contrib.linkextractors.sgml import SgmlLinkExtractor
from scrapy.http import Request
from CAA_DATA_Crawl.items import CaaDataCrawlItem
from CAA_DATA_Crawl.settings import global_spider
from CAA_DATA_Crawl.settings import DEFAULT_REQUEST_HEADERS as default_headers
from scrapy import log,FormRequest
import re,time,sys,json,MySQLdb,copy,random
from redis import Redis
from scrapy.http.cookies import CookieJar
from scrapy_redis.spiders import RedisSpider
reload(sys)
sys.setdefaultencoding( "utf-8" )

random_char_list = 'AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz0123456789_-+=!@#$%^&*'

class CaaSpiderSpider(RedisSpider):

    spider_id = global_spider.get_spider_id()
    global_spider.spider_id_add()
    name = "anjuke_spider%s"%spider_id
    allowed_domains = ['htvaluer.com']
    redis_key = 'CAA_Search:seed'
    random_list = random_char_list
    headers = default_headers

    class CaaSpiderFormRequest(FormRequest):
        def __init__(self, *args, **kwargs):
            formdata = kwargs.pop('formdata', None)
            if formdata and kwargs.get('method') is None:
                kwargs['method'] = 'POST'

            super(FormRequest, self).__init__(*args, **kwargs)

            if formdata:
                items = formdata.items() if isinstance(formdata, dict) else formdata
                querystr = str(items)
                if self.method == 'POST':
                    self.headers.setdefault(b'Content-Type', b'application/x-www-form-urlencoded')
                    self._set_body(querystr)
                else:
                    return

    def _random_openid_factory(self):
        random_field = self.random_list
        openid_new = ''
        for i in xrange(28):
            new_char = random.choice(random_field)
            openid_new += new_char
        if len(openid_new) == 28:
            return openid_new
        else:
            return

    def _item_init(self,item):
        item['Project_ID'] = ''
        item['Project_Name'] = ''
        item['City_Name'] = ''
        item['Area_Code'] = ''
        item['Area_Name'] = ''
        item['Address'] = ''
        item['Price_Avg'] = ''
        return item

    def next_requests(self):

        """Returns a request to be scheduled or none."""
        use_set = self.settings.getbool('REDIS_START_URLS_AS_SET')
        fetch_one = self.server.spop if use_set else self.server.lpop
        # XXX: Do we need to use a timeout here?
        found = 0
        while found < self.redis_batch_size:
            data = fetch_one(self.redis_key)
            if not data:
                # Queue empty.
                break
            data_dict = json.loads(data,encoding='utf-8')
            if not (data_dict.has_key('cityName') and data_dict.has_key('keyWord')):
                # Data is unavailable.
                break
            req = self._make_request_from_keyword(data_dict)
            if req:
                yield req
                found += 1
            else:
                print "Request not made from data: %s"%data

        if found:
            print"Read %s requests from '%s'"%(found, self.redis_key)


    def _get_cityID(self,cityName):

        try:
            if cityName == '重庆市':
                return '510100'
            if cityName == '成都市':
                return '500100'
            else:
                return None
        except Exception as e:
            print Exception,":",e
            return None
        


    def _make_request_from_keyword(self,data_dict):

        url = 'http://wx.htvaluer.com/WeiXin20IF/api/Common/SelectProject'
        cityName = data_dict['cityName']
        keyWord = data_dict['keyWord']
        cityTran = self._get_cityID(cityName)
        OpenId_cur = self._random_openid_factory()
        if cityTran:
            item = CaaDataCrawlItem()
            item = self._item_init(item)
            item['City_Name'] = cityName
            city_id = cityTran
            re_body_data = {"TypeCode":4,
                             "AreaCode":city_id,
                             "Address":keyWord,
                             "PageIndex":1,
                             "PageSize":20,
                             "OpenId":OpenId_cur}

            return  self.CaaSpiderFormRequest(url=url,
                            headers=self.headers,method='POST',dont_filter=True,
                            formdata=json.dumps({"data":json.dumps(re_body_data)}),
                            meta = {'item' : item,'city_id':city_id,'request_body_data':re_body_data}, 
                            callback = self.parse_item)
        else:
            return

    def parse_item(self, response):

        url = response.url
        item = coy.deepcopy(response.meta['item'])
        cur_re_body_data = response.meta['request_body_data']
        cur_city_id = response.meta['city_id']

        try:
            response_dict = json.loads(response.body)
        except Exception as e:
            print Exception,":",e
            return

        if 'Remark' in response_dict:
            if response_dict['Remark'] == "-2":
                print 'Success register the new OpenID.'
                yield self.CaaSpiderFormRequest(url=url,
                                headers=self.headers,method='POST',dont_filter=True,
                                formdata=json.dumps({"data":json.dumps(cur_re_body_data)}),
                                meta = {'item' : item,'city_id':cur_city_id,'request_body_data':cur_re_body_data}, 
                                callback = self.parse_item)

            if response_dict['Remark'] == '':
                print 'Need to change another OpenID'
                cur_re_body_data["OpenID"] = self._random_openid_factory()
                yield self.CaaSpiderFormRequest(url=url,
                                headers=self.headers,method='POST',dont_filter=True,
                                formdata=json.dumps({"data":json.dumps(cur_re_body_data)}),
                                meta = {'item' : item,'city_id':cur_city_id,'request_body_data':cur_re_body_data}, 
                                callback = self.parse_item)
        
        if 'ProjectList' in response_dict:
            ProjectList = response_dict['ProjectList']
            for Project in ProjectList:
                try:
                    re_body_data = {}
                    next_url = 'http://wx.htvaluer.com/WeiXin20IF/api/Common/EnquiryPrice'
                    item['Project_ID'] = ProjectID = Project['id']
                    item['Project_Name'] = ProjectName = Project['projectname']
                    item['Area_Code'] = AreaCode = Project['areacode']
                    item['Area_Name'] = AreaName = Project['areaname']
                    item['Address'] = Address = Project['address']
                    re_body_data['AreaCode'] = AreaCode
                    re_body_data['ProjectId'] = ProjectId
                    re_body_data['Address'] = Address
                    re_body_data['BuildArea'] = '110'
                    re_body_data['OpenId'] = self._random_openid_factory()
                    yield self.CaaSpiderFormRequest(url=next_url,
                                headers=self.headers,method='POST',dont_filter=True,
                                formdata=json.dumps({"data":json.dumps(re_body_data)}),
                                meta = {'item' : item,'request_body_data':re_body_data}, 
                                callback = self.parse_price)
                except Exception as e:
                    print Exception,":",e
                    return

            else:
                print "Do Nothing"
                return

    def parse_price(self):

        url = response.url
        item = coy.deepcopy(response.meta['item'])
        cur_re_body_data = response.meta['request_body_data']

        try:
            response_dict = json.loads(response.body)
        except Exception as e:
            print Exception,":",e
            return

        if 'Remark' in response_dict:
            if response_dict['Remark'] == "-2":
                print 'Success register the new OpenID.'
                yield self.CaaSpiderFormRequest(url=url,
                                headers=self.headers,method='POST',dont_filter=True,
                                formdata=json.dumps({"data":json.dumps(cur_re_body_data)}),
                                meta = {'item' : item,'request_body_data':cur_re_body_data}, 
                                callback = self.parse_price)

            if response_dict['Remark'] == '':
                print 'Need to change another OpenID'
                cur_re_body_data["OpenID"] = self._random_openid_factory()
                yield self.CaaSpiderFormRequest(url=url,
                                headers=self.headers,method='POST',dont_filter=True,
                                formdata=json.dumps({"data":json.dumps(cur_re_body_data)}),
                                meta = {'item' : item,'request_body_data':cur_re_body_data}, 
                                callback = self.parse_price)

        if 'ReturnCode' in response_dict and 'PriceRange' in response_dict:
            if response_dict['ReturnCode'] = '1':
                item['Price_Avg'] = response_dict['PriceRange']
                yield item
            else:
                print "Asking price ReturnCode is not 1"
                return
        else:
            print "ReturnCode or PriceRange is not in response"
            print "The response body is :"
            print response.body
            return


