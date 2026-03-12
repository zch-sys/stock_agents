from datetime import datetime, timedelta
import os
import re
from typing import List, Dict, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import time
import random
from .config_manager import load_config, setup_logging

# 导入数据库相关模块
try:
    from .database import init_db, StockNews, get_session
except ImportError as e:
    logger = setup_logging(__name__)
    logger.error(f"导入数据库模块失败: {e}")
    raise

# 配置日志
logger = setup_logging(__name__)


class StockNewsCrawler:
    """东方财富股吧新闻爬取类 - 全自动识别首次/日常爬取，无需手动传参"""
    
    # 默认配置常量
    DEFAULT_TIME_RANGE_INITIAL = 7    # 首次爬取默认7天
    DEFAULT_TIME_RANGE_DAILY = 0      # 日常爬取默认0天（当日）
    DEFAULT_RETENTION_DAYS = 30       # 数据默认保留30天
    DEFAULT_PAGE_LOAD_TIMEOUT = 15
    DEFAULT_WAIT_TIME = 10
    
    def __init__(self, token: Optional[str] = None, config_path: Optional[str] = None):
        """
        初始化新闻爬取器
        :param token: 可选的认证token（预留扩展）
        :param config_path: 自定义配置文件路径（已废弃，统一使用config/settings.yaml）
        """
        # 加载配置
        self.config = load_config()
        self.token = token or self.config.get('token', '')
        
        # 数据库配置
        self.db_url = self.config.get('data_collector', {}).get('db_url', '')
        if not self.db_url:
            raise ValueError("数据库配置未找到，请检查settings.yaml中的data_collector.db_url")
        self.engine, self.SessionLocal = init_db(self.db_url)
        
        # 基础爬取配置
        self.page_load_timeout = self.config.get('crawler', {}).get('page_load_timeout', self.DEFAULT_PAGE_LOAD_TIMEOUT)
        self.wait_time = self.config.get('crawler', {}).get('wait_time', self.DEFAULT_WAIT_TIME)
        self.retention_days = self.config.get('crawler', {}).get('retention_days', self.DEFAULT_RETENTION_DAYS)
        self.headless = self.config.get('crawler', {}).get('headless', False)
        
        # 反爬虫配置（从yaml读取）
        anti_scraping = self.config.get('crawler', {}).get('anti_scraping', {})
        self.min_delay = anti_scraping.get('min_delay', 0.5)
        self.max_delay = anti_scraping.get('max_delay', 2.0)
        self.scroll_chance = anti_scraping.get('scroll_chance', 0.7)
        self.max_news_per_run = anti_scraping.get('max_news_per_run', 50)
        self.batch_sleep = anti_scraping.get('batch_sleep', 5)
        self.batch_size = anti_scraping.get('batch_size', 5)
        
        logger.info(
            f"StockNewsCrawler 初始化完成 | "
            f"数据保留{self.retention_days}天 | "
            f"反爬虫延迟[{self.min_delay}-{self.max_delay}]秒 | "
            f"数据库:{self.db_url[:20]}..."
        )

    def init_edge_browser(self) -> webdriver.Edge:
        """初始化Edge浏览器（复用原有逻辑，配置解耦）"""
        edge_options = Options()
        
        # 反爬虫配置
        edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        edge_options.add_experimental_option('useAutomationExtension', False)
        edge_options.add_argument("--disable-blink-features=AutomationControlled")
        edge_options.add_argument("window-size=1920,1080")
        edge_options.add_argument("--disable-gpu")
        edge_options.add_argument("--disable-dev-shm-usage")
        edge_options.add_argument("--no-sandbox")
        edge_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")
        
        # 无头模式（从配置读取）
        if self.headless:
            edge_options.add_argument("--headless=new")
            logger.info("启用浏览器无界面模式")
        
        # 驱动路径处理
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            driver_path = os.path.join(project_root, "drivers", "msedgedriver.exe")
            
            if not os.path.exists(driver_path):
                driver_path = "F:\\tradingagents\\drivers\\msedgedriver.exe"
            
            if not os.path.exists(driver_path):
                import shutil
                edge_driver_path = shutil.which("msedgedriver")
                if edge_driver_path:
                    driver_path = edge_driver_path
                else:
                    raise FileNotFoundError(
                        f"Edge驱动文件未找到。请将msedgedriver.exe放在以下位置之一:\n"
                        f"1. {os.path.join(project_root, 'drivers', 'msedgedriver.exe')}\n"
                        f"2. F:\\tradingagents\\drivers\\msedgedriver.exe\n"
                        f"3. 系统PATH中的任意位置"
                    )
            
            logger.info(f"使用Edge驱动: {driver_path}")
            
            driver = webdriver.Edge(
                service=Service(driver_path),
                options=edge_options
            )
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.set_page_load_timeout(self.page_load_timeout)
            logger.info("Edge浏览器初始化成功")
            return driver
        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            raise

    # ====================== 核心新增：自动判断爬取类型 ======================
    def _get_auto_crawl_type(self, stock_code: str) -> str:
        """
        自动判断单只股票的爬取类型（核心逻辑）
        判断依据：数据库中是否有该股票近7天的新闻/公告
        - 无近7天数据 → 首次爬取(initial)
        - 有近7天数据 → 日常爬取(daily)
        """
        session = None
        try:
            session = get_session(engine=self.engine)
            # 计算近7天的时间阈值
            seven_days_ago = datetime.now() - timedelta(days=self.DEFAULT_TIME_RANGE_INITIAL)
            
            # 查询该股票近7天是否有有效数据
            has_recent_news = session.query(StockNews).filter(
                StockNews.stock_code == stock_code,
                StockNews.publish_time >= seven_days_ago
            ).first() is not None
            
            if not has_recent_news:
                logger.info(f"股票 {stock_code}：无近7天新闻/公告 → 执行首次爬取（近7天全量）")
                return "initial"
            else:
                logger.info(f"股票 {stock_code}：有近7天新闻/公告 → 执行日常爬取（仅当日）")
                return "daily"
        except Exception as e:
            logger.error(f"自动判断股票 {stock_code} 爬取类型失败，默认日常爬取: {e}")
            return "daily"  # 异常时默认日常爬取，避免全量重复爬取
        finally:
            if session:
                session.close()

    # ====================== 时间处理方法 ======================
    def parse_publish_time(self, time_str: str) -> Optional[datetime]:
        """解析发布时间字符串为datetime对象（处理跨月/跨年）"""
        try:
            time_str = re.sub(r'\s+', ' ', time_str).strip()
            now = datetime.now()
            current_year = now.year
            current_month = now.month
            
            month = int(time_str.split('-')[0])
            day = int(time_str.split('-')[1].split(' ')[0])
            
            # 处理跨年
            if month > current_month:
                year = current_year - 1
            else:
                year = current_year
                
            full_time_str = f"{year}-{time_str}"
            publish_time = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M")
            return publish_time
        except Exception as e:
            logger.error(f"时间解析失败: {time_str}, 错误: {e}")
            return None
    
    def parse_notice_time(self, time_str: str) -> Optional[datetime]:
        """解析公告日期字符串（YYYY-MM-DD）为datetime对象"""
        try:
            time_str = re.sub(r'\s+', ' ', time_str).strip()
            publish_time = datetime.strptime(time_str, "%Y-%m-%d")
            return publish_time
        except Exception as e:
            logger.error(f"公告时间解析失败: {time_str}, 错误: {e}")
            return None

    def get_crawl_time_threshold(self, crawl_type: str = "daily") -> datetime:
        """
        获取爬取时间阈值
        :param crawl_type: initial（首次，近7日）/ daily（日常，当日）
        :return: 时间阈值（早于该时间的不爬取）
        """
        if crawl_type == "initial":
            time_range = self.config.get('crawler', {}).get('time_range_days', self.DEFAULT_TIME_RANGE_INITIAL)
            threshold = datetime.now() - timedelta(days=time_range)
            logger.info(f"首次爬取时间阈值：{threshold.strftime('%Y-%m-%d %H:%M')}（近{time_range}天）")
        elif crawl_type == "daily":
            # 日常爬取：仅爬取当日（0点到当前）
            threshold = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            logger.info(f"日常爬取时间阈值：{threshold.strftime('%Y-%m-%d %H:%M')}（当日）")
        else:
            raise ValueError(f"无效的爬取类型：{crawl_type}，仅支持initial/daily")
        
        return threshold

    def is_within_crawl_range(self, publish_time: datetime, crawl_type: str) -> bool:
        """检查发布时间是否在爬取范围内"""
        threshold = self.get_crawl_time_threshold(crawl_type)
        return publish_time >= threshold

    # ====================== 数据清理方法 ======================
    def clean_old_news(self) -> int:
        """
        清理数据库中超过保留天数的新闻/公告
        :return: 清理的记录数
        """
        session = None
        try:
            session = get_session(engine=self.engine)
            # 计算清理阈值（30天前）
            clean_threshold = datetime.now() - timedelta(days=self.retention_days)
            
            # 查询需要清理的记录数
            old_news_count = session.query(StockNews).filter(
                StockNews.publish_time < clean_threshold
            ).count()
            
            if old_news_count == 0:
                logger.info(f"无超过{self.retention_days}天的旧数据，无需清理")
                return 0
            
            # 执行删除
            deleted_count = session.query(StockNews).filter(
                StockNews.publish_time < clean_threshold
            ).delete()
            session.commit()
            
            logger.info(f"成功清理 {deleted_count} 条超过{self.retention_days}天的新闻/公告")
            return deleted_count
        except Exception as e:
            if session:
                session.rollback()
            logger.error(f"清理旧数据失败: {e}")
            raise
        finally:
            if session:
                session.close()

    # ====================== 核心爬取方法（优化返回值） ======================
    def crawl_single_stock(self, stock_code: str, crawl_type: str = "daily") -> Tuple[List[Dict], int]:
        """
        爬取单只股票的新闻/公告（区分首次/日常模式）
        :param stock_code: 股票代码
        :param crawl_type: initial（首次）/ daily（日常）
        :return: (爬取的新闻列表, 成功保存的条数)
        """
        if crawl_type not in ["initial", "daily"]:
            raise ValueError(f"爬取类型仅支持initial/daily，当前为：{crawl_type}")
        
        all_news = []
        saved_count = 0
        driver = None
        
        try:
            driver = self.init_edge_browser()
            logger.info(f"开始爬取股票 {stock_code} - 模式：{crawl_type}")
            
            # 爬取新闻和公告
            news_list = self._crawl_content(driver, stock_code, "news", "1,f", "资讯", crawl_type)
            notice_list = self._crawl_content(driver, stock_code, "notices", "3,f", "公告", crawl_type)
            
            all_news = news_list + notice_list
            logger.info(f"股票 {stock_code} 爬取完成 - 共获取 {len(all_news)} 条有效数据（模式：{crawl_type}）")
            
            # 保存到数据库并统计保存数
            if all_news:
                saved_count = self.save_news_to_db(all_news)
            
            return all_news, saved_count
        except Exception as e:
            logger.error(f"股票 {stock_code} 爬取失败（模式：{crawl_type}）: {e}")
            return [], 0
        finally:
            if driver:
                driver.quit()
                logger.info(f"股票 {stock_code} 浏览器已关闭")

    def _crawl_content(self, driver: webdriver.Edge, stock_code: str, content_type: str, 
                      page_param: str, log_name: str, crawl_type: str) -> List[Dict]:
        """
        通用爬取方法（解耦浏览器实例，支持爬取类型）
        :param driver: 浏览器实例（复用，减少启动开销）
        :param stock_code: 股票代码
        :param content_type: news/notices
        :param page_param: 页面参数
        :param log_name: 日志显示名称（资讯/公告）
        :param crawl_type: initial/daily
        :return: 有效内容列表
        """
        content_list = []
        try:
            # 访问目标URL
            target_url = f"https://guba.eastmoney.com/list,{stock_code},{page_param}.html"
            driver.get(target_url)
            logger.info(f"已访问{log_name}页面: {target_url}")
            self._random_sleep()
            
            # 关闭弹窗
            self._close_popups(driver)
            
            # 等待内容列表加载
            WebDriverWait(driver, self.wait_time).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.default_list tbody.listbody tr.listitem"))
            )
            
            # 随机滚动页面（反爬虫）
            self._random_scroll(driver)
            
            # 获取所有内容项（首次爬取无条数限制，日常爬取也无限制）
            if content_type == "notices":
                items = driver.find_elements(By.CSS_SELECTOR, "table.default_list tbody.listbody tr.listitem.notice_item")
            else:
                items = driver.find_elements(By.CSS_SELECTOR, "table.default_list tbody.listbody tr.listitem")
            
            logger.info(f"股票 {stock_code} 找到 {len(items)} 个{log_name}项（模式：{crawl_type}）")
            
            if not items:
                logger.warning(f"股票 {stock_code} 未找到{log_name}项")
                return content_list
            
            # 批量处理（按batch_size分批）
            for batch_idx in range(0, len(items), self.batch_size):
                batch_items = items[batch_idx:batch_idx + self.batch_size]
                logger.info(f"处理第 {batch_idx//self.batch_size + 1} 批{log_name}，共 {len(batch_items)} 条")
                
                for index, item in enumerate(batch_items):
                    try:
                        self._random_sleep()
                        
                        # 提取发布时间
                        pub_time_elem = item.find_element(By.CSS_SELECTOR, "td .pub_time")
                        pub_time_str = pub_time_elem.text.strip()
                        
                        # 解析时间
                        if content_type == "notices":
                            publish_time = self.parse_notice_time(pub_time_str)
                        else:
                            publish_time = self.parse_publish_time(pub_time_str)
                        
                        if not publish_time:
                            logger.warning(f"股票 {stock_code} 第 {index+1} 条{log_name} - 时间解析失败，跳过")
                            continue
                        
                        # 检查是否在爬取范围内
                        if not self.is_within_crawl_range(publish_time, crawl_type):
                            logger.info(f"股票 {stock_code} 第 {index+1} 条{log_name} - 超出爬取范围，跳过")
                            continue
                        
                        # 提取链接
                        link_elem = item.find_element(By.CSS_SELECTOR, "td .title a.PO")
                        link = link_elem.get_attribute("href")
                        if link and link.startswith("/"):
                            link = "https://guba.eastmoney.com" + link
                        
                        if not link or not link.startswith("http"):
                            logger.warning(f"股票 {stock_code} 第 {index+1} 条{log_name} - 链接无效，跳过")
                            continue
                        
                        # 爬取详情页
                        detail_data = self._crawl_detail_page(driver, link, content_type, publish_time)
                        if detail_data:
                            detail_data["stock_code"] = stock_code
                            content_list.append(detail_data)
                            logger.info(f"股票 {stock_code} 第 {index+1} 条{log_name}提取成功: {detail_data['title'][:50]}...")
                        
                        # 检查总条数上限（防止爬取过多）
                        if len(content_list) >= self.max_news_per_run:
                            logger.info(f"股票 {stock_code} {log_name} 已达最大爬取数{self.max_news_per_run}，停止")
                            break
                    
                    except Exception as e:
                        logger.error(f"股票 {stock_code} 处理第 {index+1} 条{log_name}时出错: {e}")
                        # 异常恢复：关闭多余标签页
                        self._recover_browser_state(driver)
                
                # 每批处理完休息
                logger.info(f"股票 {stock_code} 第 {batch_idx//self.batch_size + 1} 批{log_name}处理完成，休息{self.batch_sleep}秒")
                time.sleep(self.batch_sleep)
            
            logger.info(f"股票 {stock_code} {log_name} 爬取完成，共获取 {len(content_list)} 条有效数据")
            return content_list
        except Exception as e:
            logger.error(f"股票 {stock_code} {log_name} 爬取失败: {e}")
            return []

    def _crawl_detail_page(self, driver: webdriver.Edge, link: str, content_type: str, 
                          publish_time: datetime) -> Optional[Dict]:
        """爬取详情页内容（解耦，便于复用）"""
        try:
            # 新标签页打开
            driver.execute_script(f"window.open('{link}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
            self._random_sleep()
            
            # 提取标题
            title_elem = WebDriverWait(driver, self.wait_time).until(
                EC.presence_of_element_located((By.CLASS_NAME, "cn-title"))
            )
            title = title_elem.text.strip()
            
            # 提取内容
            content_elems = driver.find_elements(By.TAG_NAME, "p")
            content = "\n".join([e.text.strip() for e in content_elems if e.text.strip()])
            
            if not content:
                logger.warning(f"详情页内容为空: {link}")
                return None
            
            return {
                "content_type": content_type,
                "publish_time": publish_time.strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
                "content": content[:10000]  # 限制长度
            }
        except Exception as e:
            logger.error(f"详情页爬取失败: {link}, 错误: {e}")
            return None
        finally:
            # 关闭详情页，切回列表页
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

    # ====================== 辅助方法 ======================
    def _close_popups(self, driver: webdriver.Edge) -> None:
        """关闭页面弹窗"""
        try:
            close_buttons = driver.find_elements(By.XPATH, "//img[contains(@src, 'close')]")
            for button in close_buttons[:2]:
                try:
                    if button.is_displayed():
                        button.click()
                        logger.info("已关闭页面弹窗")
                        self._random_sleep()
                        break
                except:
                    continue
        except Exception as e:
            logger.debug(f"页面无弹窗或关闭失败: {e}")

    def _random_sleep(self) -> None:
        """随机延迟（使用配置中的参数）"""
        sleep_time = random.uniform(self.min_delay, self.max_delay)
        time.sleep(sleep_time)

    def _random_scroll(self, driver: webdriver.Edge) -> None:
        """随机滚动页面（反爬虫）"""
        if random.random() < self.scroll_chance:
            # 随机滚动到页面中间或底部
            scroll_height = random.choice([500, 1000, driver.execute_script("return document.body.scrollHeight")])
            driver.execute_script(f"window.scrollTo(0, {scroll_height});")
            self._random_sleep()
            logger.debug("执行随机页面滚动（反爬虫）")

    def _recover_browser_state(self, driver: webdriver.Edge) -> None:
        """恢复浏览器状态（关闭多余标签页）"""
        try:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except Exception as e:
            logger.debug(f"浏览器状态恢复失败: {e}")

    # ====================== 数据库操作 ======================
    def save_news_to_db(self, news_list: List[Dict]) -> int:
        """
        保存新闻到数据库（去重）
        :param news_list: 新闻列表
        :return: 成功保存的条数
        """
        if not news_list:
            logger.warning("无新闻数据可保存")
            return 0
        
        session = None
        try:
            session = get_session(engine=self.engine)
            saved_count = 0
            
            for news in news_list:
                # 转换发布时间
                try:
                    if isinstance(news["publish_time"], str):
                        publish_time = datetime.strptime(news["publish_time"], "%Y-%m-%d %H:%M:%S")
                    else:
                        publish_time = news["publish_time"]
                except Exception as e:
                    logger.error(f"时间转换失败: {news['publish_time']}, 错误: {e}")
                    publish_time = datetime.now()
                
                # 去重检查
                existing_news = session.query(StockNews).filter(
                    StockNews.stock_code == news["stock_code"],
                    StockNews.publish_time == publish_time,
                    StockNews.title == news["title"]
                ).first()
                
                if existing_news:
                    logger.info(f"新闻已存在，跳过 | 股票:{news['stock_code']} | 标题: {news['title'][:50]}...")
                    continue
                
                # 保存
                stock_news = StockNews(
                    stock_code=news["stock_code"],
                    publish_time=publish_time,
                    title=news["title"],
                    content=news["content"],
                    content_type=news.get("content_type", "news")
                )
                session.add(stock_news)
                saved_count += 1
            
            session.commit()
            logger.info(f"成功保存 {saved_count}/{len(news_list)} 条新闻到数据库")
            return saved_count
        except Exception as e:
            if session:
                session.rollback()
            logger.error(f"保存新闻到数据库失败: {e}")
            raise
        finally:
            if session:
                session.close()

    # ====================== 批量爬取入口（核心修改：全自动） ======================
    def batch_crawl(self, stock_codes: List[str], crawl_type: str = "auto") -> Dict:
        """
        批量爬取股票新闻/公告（默认全自动，无需手动传参）
        :param stock_codes: 股票代码列表
        :param crawl_type: auto（自动）/ initial（强制首次）/ daily（强制日常）
        :return: 爬取结果统计
        """
        if not stock_codes:
            raise ValueError("股票代码列表不能为空")
        if crawl_type not in ["auto", "initial", "daily"]:
            raise ValueError(f"爬取类型仅支持auto/initial/daily，当前为：{crawl_type}")
        
        # 第一步：清理旧数据
        logger.info("========== 开始清理旧数据 ==========")
        deleted_count = self.clean_old_news()
        
        # 第二步：批量爬取
        logger.info("========== 开始批量爬取（全自动模式） ==========")
        result_stats = {
            "total_stocks": len(stock_codes),
            "success_stocks": 0,
            "failed_stocks": [],
            "total_news": 0,
            "saved_news": 0,  # 精准统计保存数
            "deleted_old_news": deleted_count,
            "crawl_type": crawl_type,
            "stock_detail": {}  # 每只股票的详细统计
        }
        
        for idx, stock_code in enumerate(stock_codes):
            logger.info(f"\n========== 处理第 {idx+1}/{len(stock_codes)} 只股票：{stock_code} ==========")
            try:
                # 自动判断爬取类型（核心逻辑）
                if crawl_type == "auto":
                    current_type = self._get_auto_crawl_type(stock_code)
                else:
                    current_type = crawl_type
                    logger.info(f"强制指定爬取模式：{current_type}")
                
                # 爬取单只股票
                news_list, saved_count = self.crawl_single_stock(stock_code, current_type)
                
                # 更新统计
                result_stats["total_news"] += len(news_list)
                result_stats["saved_news"] += saved_count
                result_stats["success_stocks"] += 1
                result_stats["stock_detail"][stock_code] = {
                    "crawl_type": current_type,
                    "crawled_news": len(news_list),
                    "saved_news": saved_count,
                    "status": "success"
                }
            except Exception as e:
                logger.error(f"股票 {stock_code} 处理失败: {e}")
                result_stats["failed_stocks"].append(stock_code)
                result_stats["stock_detail"][stock_code] = {
                    "crawl_type": "unknown",
                    "crawled_news": 0,
                    "saved_news": 0,
                    "status": "failed",
                    "error": str(e)[:100]
                }
        
        # 第三步：输出统计结果
        logger.info("\n========== 批量爬取完成 ==========")
        logger.info(f"爬取模式：{crawl_type}（auto=全自动识别，initial=强制首次，daily=强制日常）")
        logger.info(f"处理股票总数：{result_stats['total_stocks']}")
        logger.info(f"成功处理：{result_stats['success_stocks']}")
        logger.info(f"失败处理：{len(result_stats['failed_stocks'])} ({result_stats['failed_stocks']})")
        logger.info(f"爬取新闻总数：{result_stats['total_news']}")
        logger.info(f"成功保存条数：{result_stats['saved_news']}")
        logger.info(f"清理旧数据条数：{result_stats['deleted_old_news']}")
        
        # 输出每只股票的详细统计（可选）
        logger.info("\n========== 单只股票详细统计 ==========")
        for stock_code, detail in result_stats["stock_detail"].items():
            logger.info(f"{stock_code} | 模式：{detail['crawl_type']} | 爬取：{detail['crawled_news']} | 保存：{detail['saved_news']} | 状态：{detail['status']}")
        
        return result_stats

