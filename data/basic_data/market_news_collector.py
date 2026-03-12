"""
大盘新闻爬虫 - 东方财富财经新闻
爬取地址: https://finance.eastmoney.com/a/cdfsd_{}.html
参考: newsdata.py 个股新闻爬取方法
"""
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
from .database import MarketNews, get_session_context

logger = setup_logging(__name__)


class MarketNewsCollector:
    """大盘新闻爬取类 - 东方财富财经新闻（参考StockNewsCrawler实现）"""
    
    # 默认配置常量
    DEFAULT_RETENTION_DAYS = 15       # 数据默认保留7天
    DEFAULT_PAGE_LOAD_TIMEOUT = 15
    DEFAULT_WAIT_TIME = 10
    
    def __init__(self):
        """初始化大盘新闻爬取器"""
        # 加载配置
        self.config = load_config()
        
        # 爬取配置（从 settings.yaml 的 market_news_crawler 读取）
        crawler_config = self.config.get('market_news_crawler', {})
        
        self.page_load_timeout = crawler_config.get('page_load_timeout', self.DEFAULT_PAGE_LOAD_TIMEOUT)
        self.wait_time = crawler_config.get('wait_time', self.DEFAULT_WAIT_TIME)
        self.retention_days = crawler_config.get('retention_days', self.DEFAULT_RETENTION_DAYS)
        self.headless = crawler_config.get('headless', False)
        
        # 反爬虫配置
        anti_scraping = crawler_config.get('anti_scraping', {})
        self.min_delay = anti_scraping.get('min_delay', 0.5)
        self.max_delay = anti_scraping.get('max_delay', 2.0)
        self.scroll_chance = anti_scraping.get('scroll_chance', 0.7)
        self.max_news_per_run = anti_scraping.get('max_news_per_run', 50)
        self.batch_sleep = anti_scraping.get('batch_sleep', 5)
        self.batch_size = anti_scraping.get('batch_size', 5)
        
        # 东方财富财经新闻页面URL模板
        self.base_url_template = "https://finance.eastmoney.com/a/cdfsd_{}.html"
        
        logger.info(
            f"MarketNewsCollector 初始化完成 | "
            f"数据保留{self.retention_days}天 | "
            f"反爬虫延迟[{self.min_delay}-{self.max_delay}]秒"
        )

    def init_edge_browser(self) -> webdriver.Edge:
        """初始化Edge浏览器"""
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
        edge_options.add_argument("--disable-smart-screen")
        edge_options.add_argument("--disable-features=msSmartScreenProtection")
        # 无头模式
        if self.headless:
            edge_options.add_argument("--headless=new")
            logger.info("启用浏览器无界面模式")
        
        # 驱动路径处理
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            driver_path = os.path.join(project_root, "data", "basic_data", "drivers", "msedgedriver.exe")
            
            if not os.path.exists(driver_path):
                driver_path = os.path.join(project_root, "drivers", "msedgedriver.exe")
            
            if not os.path.exists(driver_path):
                import shutil
                edge_driver_path = shutil.which("msedgedriver")
                if edge_driver_path:
                    driver_path = edge_driver_path
                else:
                    raise FileNotFoundError(
                        f"Edge驱动文件未找到。请将msedgedriver.exe放在以下位置之一:\n"
                        f"1. {os.path.join(project_root, 'drivers', 'msedgedriver.exe')}\n"
                        f"2. 系统PATH中的任意位置"
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

    def parse_publish_time(self, time_str: str) -> Optional[datetime]:
        """
        解析发布时间字符串为datetime对象
        格式: "2026年02月22日 00:21"
        """
        try:
            time_str = re.sub(r'\s+', ' ', time_str).strip()
            # 格式: 2026年02月22日 00:21
            time_str = time_str.replace('年', '-').replace('月', '-').replace('日', '')
            publish_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            return publish_time
        except Exception as e:
            logger.error(f"时间解析失败: {time_str}, 错误: {e}")
            return None

    def is_within_24_hours(self, publish_time: datetime) -> bool:
        """检查发布时间是否在最近24小时内"""
        threshold = datetime.now() - timedelta(hours=24)
        return publish_time >= threshold

    # ====================== 数据清理方法 ======================
    def clean_old_news(self, days: int = None) -> int:
        """
        清理数据库中超过保留天数的新闻
        :param days: 保留天数，默认使用配置值
        :return: 清理的记录数
        """
        if days is None:
            days = self.retention_days
        
        with get_session_context() as session:
            threshold = datetime.now() - timedelta(days=days)
            deleted_count = session.query(MarketNews).filter(
                MarketNews.publish_time < threshold
            ).delete()
            logger.info(f"清理 {deleted_count} 条超过 {days} 天的大盘新闻")
            return deleted_count

    # ====================== 核心爬取方法 ======================
    def fetch_all(self) -> Dict:
        """
        获取大盘新闻主入口（兼容scheduler调用）
        :return: 爬取结果统计
        """
        logger.info("=" * 50)
        logger.info("开始爬取东方财富大盘新闻")
        logger.info("=" * 50)
        
        news_list, saved_count = self.crawl_market_news()
        
        # 清理旧数据
        deleted_count = self.clean_old_news()
        
        result = {
            "news_flash": {"fetched": len(news_list), "saved": saved_count},
            "cleaned": deleted_count,
            "total_saved": saved_count
        }
        
        logger.info("=" * 50)
        logger.info(f"完成: 爬取{len(news_list)}条, 保存{saved_count}条, 清理{deleted_count}条")
        logger.info("=" * 50)
        
        return result

    def crawl_market_news(self, max_pages: int = 3) -> Tuple[List[Dict], int]:
        """
        爬取东方财富财经新闻
        :param max_pages: 最大爬取页数
        :return: (爬取的新闻列表, 成功保存的条数)
        """
        all_news = []
        saved_count = 0
        driver = None
        
        try:
            driver = self.init_edge_browser()
            logger.info(f"开始爬取东方财富财经新闻，最大页数: {max_pages}")
            
            for page in range(1, max_pages + 1):
                try:
                    page_url = self.base_url_template.format(page)
                    logger.info(f"正在爬取第 {page} 页: {page_url}")
                    
                    news_list, page_saved = self._crawl_single_page(driver, page_url, page)
                    all_news.extend(news_list)
                    saved_count += page_saved
                    
                    logger.info(f"第 {page} 页完成: 获取 {len(news_list)} 条, 保存 {page_saved} 条")
                    
                    # 页间休息
                    if page < max_pages:
                        sleep_time = random.uniform(self.batch_sleep, self.batch_sleep + 2)
                        logger.info(f"页间休息 {sleep_time:.1f} 秒...")
                        time.sleep(sleep_time)
                
                except Exception as e:
                    logger.error(f"爬取第 {page} 页失败: {e}")
                    continue
            
            logger.info(f"爬取完成: 共获取 {len(all_news)} 条新闻，保存 {saved_count} 条")
            return all_news, saved_count
            
        except Exception as e:
            logger.error(f"爬取大盘新闻失败: {e}")
            return [], 0
        finally:
            if driver:
                driver.quit()
                logger.info("浏览器已关闭")

    def _crawl_single_page(self, driver: webdriver.Edge, page_url: str, page_num: int) -> Tuple[List[Dict], int]:
        """
        爬取单个页面的新闻
        :param driver: 浏览器实例
        :param page_url: 页面URL
        :param page_num: 页码
        :return: (新闻列表, 保存条数)
        """
        news_list = []
        
        try:
            # 访问列表页
            driver.get(page_url)
            self._random_sleep()
            
            # 关闭弹窗/广告
            self._close_popups(driver)
            
            # 等待JS动态加载新闻列表（页面通过AJAX加载内容）
            time.sleep(3)  # 等待AJAX请求完成
            
            # 等待新闻列表容器出现内容
            try:
                WebDriverWait(driver, self.wait_time).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "#newsListContent li")) > 0
                )
            except:
                logger.warning(f"第 {page_num} 页等待新闻列表超时，尝试继续")
            
            # 关闭弹窗（二次确认）
            self._close_popups(driver)
            
            # 获取新闻项 - 东方财富动态加载的新闻列表
            news_items = driver.find_elements(By.CSS_SELECTOR, "#newsListContent li")
            
            logger.info(f"第 {page_num} 页找到 {len(news_items)} 条新闻项")
            
            if not news_items:
                logger.warning(f"第 {page_num} 页未找到新闻项")
                return [], 0
            
            # 处理每条新闻
            for index, item in enumerate(news_items):
                try:
                    self._random_sleep()
                    
                    # 提取发布时间 - <p class="time">2026年02月22日 00:21</p>
                    try:
                        time_elem = item.find_element(By.XPATH, ".//p[@class='time']")
                        pub_time_str = time_elem.text.strip()
                    except:
                        # 尝试其他选择器
                        try:
                            time_elem = item.find_element(By.CSS_SELECTOR, ".time")
                            pub_time_str = time_elem.text.strip()
                        except:
                            logger.warning(f"第 {index+1} 条新闻 - 未找到时间元素，跳过")
                            continue
                    
                    # 解析时间
                    publish_time = self.parse_publish_time(pub_time_str)
                    if not publish_time:
                        logger.warning(f"第 {index+1} 条新闻 - 时间解析失败: {pub_time_str}，跳过")
                        continue
                    
                    # 检查是否在24小时内（日常爬取只获取最近24小时）
                    if not self.is_within_24_hours(publish_time):
                        logger.debug(f"第 {index+1} 条新闻 - 超出24小时: {pub_time_str}，跳过")
                        continue
                    
                    # 提取链接和标题 - XPath: .//div[2]/p[1]/a
                    try:
                        link_elem = item.find_element(By.XPATH, ".//p[@class='title']/a")
                        link = link_elem.get_attribute("href")
                        title = link_elem.text.strip()
                    except:
                        # 尝试其他选择器
                        try:
                            link_elem = item.find_element(By.CSS_SELECTOR, "p.title a")
                            link = link_elem.get_attribute("href")
                            title = link_elem.text.strip()
                        except:
                            logger.warning(f"第 {index+1} 条新闻 - 未找到标题链接，跳过")
                            continue
                    
                    if not link or not link.startswith("http"):
                        logger.warning(f"第 {index+1} 条新闻 - 链接无效: {link}，跳过")
                        continue
                    
                    if not title:
                        logger.warning(f"第 {index+1} 条新闻 - 标题为空，跳过")
                        continue
                    
                    # 爬取详情页
                    detail_data = self._crawl_detail_page(driver, link, publish_time, title)
                    if detail_data:
                        news_list.append(detail_data)
                        logger.info(f"第 {index+1} 条新闻提取成功: {title[:50]}...")
                    
                    # 检查最大爬取数
                    if len(news_list) >= self.max_news_per_run:
                        logger.info(f"已达最大爬取数 {self.max_news_per_run}，停止")
                        break
                
                except Exception as e:
                    logger.error(f"处理第 {index+1} 条新闻时出错: {e}")
                    self._recover_browser_state(driver)
                    continue
            
            # 保存到数据库
            saved_count = 0
            if news_list:
                saved_count = self._save_news_to_db(news_list)
            
            return news_list, saved_count
            
        except Exception as e:
            logger.error(f"爬取页面失败: {page_url}, 错误: {e}")
            return [], 0

    def _crawl_detail_page(self, driver: webdriver.Edge, link: str, publish_time: datetime, title: str) -> Optional[Dict]:
        """
        爬取详情页内容
        :param driver: 浏览器实例
        :param link: 详情页链接
        :param publish_time: 发布时间
        :param title: 标题
        :return: 新闻详情字典
        """
        try:
            # 新标签页打开
            driver.execute_script(f"window.open('{link}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
            self._random_sleep()
            
            # 等待页面加载
            WebDriverWait(driver, self.wait_time).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # 提取标题 - <div class="title">特朗普：原本10%的全球进口关税税率将升至15%</div>
            try:
                title_elem = driver.find_element(By.CSS_SELECTOR, "div.title")
                detail_title = title_elem.text.strip()
                if detail_title:
                    title = detail_title
            except:
                logger.debug(f"未找到详情页标题元素，使用列表页标题")
            
            # 提取内容 - <div class="txtinfos" id="ContentBody">
            try:
                content_elem = driver.find_element(By.ID, "ContentBody")
                # 提取所有p标签内容
                p_elems = content_elem.find_elements(By.TAG_NAME, "p")
                content_parts = []
                for p in p_elems:
                    text = p.text.strip()
                    # 过滤广告和无用内容
                    if text and not text.startswith("在东方财富看资讯") and not text.startswith("（文章来源："):
                        content_parts.append(text)
                
                content = "\n".join(content_parts)
            except:
                # 尝试其他选择器
                try:
                    content_elem = driver.find_element(By.CSS_SELECTOR, ".txtinfos")
                    content = content_elem.text.strip()
                except:
                    logger.warning(f"详情页内容提取失败: {link}")
                    content = ""
            
            if not content:
                logger.warning(f"详情页内容为空: {link}")
                return None
            
            return {
                "news_type": "market_news",
                "publish_time": publish_time,
                "title": title,
                "content": content[:10000],  # 限制长度
                "source": "eastmoney"
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
        """关闭页面弹窗/广告（参考newsdata.py实现）"""
        try:
            # 方法1: 查找关闭按钮（通过图片src包含close）
            close_buttons = driver.find_elements(By.XPATH, "//img[contains(@src, 'close')]")
            for button in close_buttons[:2]:  # 最多关闭2个弹窗
                try:
                    if button.is_displayed():
                        button.click()
                        logger.info("已关闭页面弹窗/广告")
                        self._random_sleep()
                        break
                except:
                    continue
            
            # 方法2: 查找常见的关闭按钮class
            close_selectors = [
                ".close-btn", ".close", ".popup-close", ".ad-close",
                "[class*='close']", "[class*='shut']", ".dialog-close"
            ]
            for selector in close_selectors:
                try:
                    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in buttons[:1]:
                        if btn.is_displayed():
                            btn.click()
                            logger.info(f"已关闭弹窗: {selector}")
                            self._random_sleep()
                            break
                except:
                    continue
                    
            # 方法3: 按ESC键关闭模态框
            try:
                from selenium.webdriver.common.keys import Keys
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
                logger.debug("尝试按ESC关闭弹窗")
            except:
                pass
                
        except Exception as e:
            logger.debug(f"关闭弹窗失败或无弹窗: {e}")

    def _random_sleep(self) -> None:
        """随机延迟"""
        sleep_time = random.uniform(self.min_delay, self.max_delay)
        time.sleep(sleep_time)

    def _random_scroll(self, driver: webdriver.Edge) -> None:
        """随机滚动页面（反爬虫）"""
        if random.random() < self.scroll_chance:
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
    def _save_news_to_db(self, news_list: List[Dict]) -> int:
        """
        保存新闻到数据库（去重）
        :param news_list: 新闻列表
        :return: 成功保存的条数
        """
        if not news_list:
            logger.warning("无新闻数据可保存")
            return 0
        
        saved_count = 0
        
        with get_session_context() as session:
            for news in news_list:
                try:
                    # 去重检查（根据标题+发布时间）
                    existing = session.query(MarketNews).filter(
                        MarketNews.title == news["title"],
                        MarketNews.publish_time == news["publish_time"]
                    ).first()
                    
                    if existing:
                        logger.debug(f"新闻已存在，跳过: {news['title'][:50]}...")
                        continue
                    
                    # 创建新记录
                    market_news = MarketNews(
                        news_type=news.get("news_type", "market_news"),
                        publish_time=news["publish_time"],
                        title=news["title"],
                        content=news.get("content"),
                        source=news.get("source", "eastmoney")
                    )
                    session.add(market_news)
                    saved_count += 1
                    
                except Exception as e:
                    logger.error(f"保存新闻失败: {e}")
                    continue
        
        logger.info(f"成功保存 {saved_count}/{len(news_list)} 条大盘新闻到数据库")
        return saved_count

    # ====================== 首次收集方法 ======================
    def fetch_initial_news(self, days: int = 15) -> Dict:
        """
        首次收集：爬取近N天的大盘新闻（用于初始化数据库）
        :param days: 收集最近N天的新闻，默认15天
        :return: 爬取结果统计
        """
        logger.info("=" * 50)
        logger.info(f"开始首次收集大盘新闻（近 {days} 天）")
        logger.info("=" * 50)
        
        all_news = []
        total_saved = 0
        
        try:
            # 计算需要爬取的页数（每页约20条新闻，10天约需10-15页）
            # 东方财富每页显示约20条，我们多爬几页确保覆盖
            max_pages = min(days * 2, 20)  # 最多20页
            
            news_list, saved_count = self._crawl_market_news_extended(max_pages=max_pages, days=days)
            all_news.extend(news_list)
            total_saved = saved_count
            
            logger.info(f"首次收集完成: 共获取 {len(all_news)} 条，保存 {total_saved} 条")
            
        except Exception as e:
            logger.error(f"首次收集大盘新闻失败: {e}")
        
        result = {
            "total_fetched": len(all_news),
            "total_saved": total_saved,
            "days_covered": days
        }
        
        logger.info("=" * 50)
        logger.info(f"首次收集结果: 获取{len(all_news)}条, 保存{total_saved}条")
        logger.info("=" * 50)
        
        return result
    
    def _crawl_market_news_extended(self, max_pages: int = 20, days: int = 10) -> Tuple[List[Dict], int]:
        """
        爬取指定天数的新闻（扩展版本，用于首次收集）
        :param max_pages: 最大爬取页数
        :param days: 收集最近N天的新闻
        :return: (爬取的新闻列表, 成功保存的条数)
        """
        all_news = []
        saved_count = 0
        driver = None
        
        # 计算时间阈值
        time_threshold = datetime.now() - timedelta(days=days)
        logger.info(f"只收集 {time_threshold.strftime('%Y-%m-%d %H:%M')} 之后的新闻")
        
        try:
            driver = self.init_edge_browser()
            logger.info(f"开始爬取东方财富财经新闻（扩展模式），最大页数: {max_pages}，天数: {days}")
            
            for page in range(1, max_pages + 1):
                try:
                    page_url = self.base_url_template.format(page)
                    logger.info(f"正在爬取第 {page} 页: {page_url}")
                    
                    news_list, page_saved = self._crawl_single_page_extended(
                        driver, page_url, page, time_threshold
                    )
                    
                    # 如果本页没有获取到任何新闻（可能已超出时间范围），停止爬取
                    if not news_list:
                        logger.info(f"第 {page} 页未获取到符合条件的新闻，停止爬取")
                        break
                    
                    all_news.extend(news_list)
                    saved_count += page_saved
                    
                    logger.info(f"第 {page} 页完成: 获取 {len(news_list)} 条, 保存 {page_saved} 条")
                    
                    # 页间休息
                    if page < max_pages:
                        sleep_time = random.uniform(self.batch_sleep, self.batch_sleep + 2)
                        logger.info(f"页间休息 {sleep_time:.1f} 秒...")
                        time.sleep(sleep_time)
                
                except Exception as e:
                    logger.error(f"爬取第 {page} 页失败: {e}")
                    continue
            
            logger.info(f"扩展爬取完成: 共获取 {len(all_news)} 条新闻，保存 {saved_count} 条")
            return all_news, saved_count
            
        except Exception as e:
            logger.error(f"扩展爬取大盘新闻失败: {e}")
            return [], 0
        finally:
            if driver:
                driver.quit()
                logger.info("浏览器已关闭")
    
    def _crawl_single_page_extended(
        self, 
        driver: webdriver.Edge, 
        page_url: str, 
        page_num: int,
        time_threshold: datetime
    ) -> Tuple[List[Dict], int]:
        """
        爬取单个页面的新闻（扩展版本，支持自定义时间阈值）
        :param driver: 浏览器实例
        :param page_url: 页面URL
        :param page_num: 页码
        :param time_threshold: 时间阈值，早于此时间的新闻将被跳过
        :return: (新闻列表, 保存条数)
        """
        news_list = []
        stop_crawling = False  # 标记是否应该停止爬取
        
        try:
            # 访问列表页
            driver.get(page_url)
            self._random_sleep()
            
            # 关闭弹窗/广告
            self._close_popups(driver)
            
            # 等待JS动态加载新闻列表
            time.sleep(3)
            
            # 等待新闻列表容器出现内容
            try:
                WebDriverWait(driver, self.wait_time).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "#newsListContent li")) > 0
                )
            except:
                logger.warning(f"第 {page_num} 页等待新闻列表超时，尝试继续")
            
            # 关闭弹窗（二次确认）
            self._close_popups(driver)
            
            # 获取新闻项
            news_items = driver.find_elements(By.CSS_SELECTOR, "#newsListContent li")
            
            logger.info(f"第 {page_num} 页找到 {len(news_items)} 条新闻项")
            
            if not news_items:
                logger.warning(f"第 {page_num} 页未找到新闻项")
                return [], 0
            
            # 处理每条新闻
            for index, item in enumerate(news_items):
                try:
                    self._random_sleep()
                    
                    # 提取发布时间
                    try:
                        time_elem = item.find_element(By.XPATH, ".//p[@class='time']")
                        pub_time_str = time_elem.text.strip()
                    except:
                        try:
                            time_elem = item.find_element(By.CSS_SELECTOR, ".time")
                            pub_time_str = time_elem.text.strip()
                        except:
                            logger.warning(f"第 {index+1} 条新闻 - 未找到时间元素，跳过")
                            continue
                    
                    # 解析时间
                    publish_time = self.parse_publish_time(pub_time_str)
                    if not publish_time:
                        logger.warning(f"第 {index+1} 条新闻 - 时间解析失败: {pub_time_str}，跳过")
                        continue
                    
                    # 检查是否在指定时间范围内
                    if publish_time < time_threshold:
                        logger.info(f"第 {index+1} 条新闻 - 超出时间范围: {pub_time_str}，停止本页爬取")
                        stop_crawling = True
                        break
                    
                    # 提取链接和标题
                    try:
                        link_elem = item.find_element(By.XPATH, ".//p[@class='title']/a")
                        link = link_elem.get_attribute("href")
                        title = link_elem.text.strip()
                    except:
                        try:
                            link_elem = item.find_element(By.CSS_SELECTOR, "p.title a")
                            link = link_elem.get_attribute("href")
                            title = link_elem.text.strip()
                        except:
                            logger.warning(f"第 {index+1} 条新闻 - 未找到标题链接，跳过")
                            continue
                    
                    if not link or not link.startswith("http"):
                        logger.warning(f"第 {index+1} 条新闻 - 链接无效: {link}，跳过")
                        continue
                    
                    if not title:
                        logger.warning(f"第 {index+1} 条新闻 - 标题为空，跳过")
                        continue
                    
                    # 爬取详情页
                    detail_data = self._crawl_detail_page(driver, link, publish_time, title)
                    if detail_data:
                        news_list.append(detail_data)
                        logger.info(f"第 {index+1} 条新闻提取成功: {title[:50]}...")
                    
                    # 检查最大爬取数（首次收集放宽限制）
                    if len(news_list) >= self.max_news_per_run * 3:
                        logger.info(f"已达最大爬取数 {self.max_news_per_run * 3}，停止")
                        break
                
                except Exception as e:
                    logger.error(f"处理第 {index+1} 条新闻时出错: {e}")
                    self._recover_browser_state(driver)
                    continue
            
            # 如果本页所有新闻都超出时间范围，返回空列表
            if stop_crawling and not news_list:
                return [], 0
            
            # 保存到数据库
            saved_count = 0
            if news_list:
                saved_count = self._save_news_to_db(news_list)
            
            return news_list, saved_count
            
        except Exception as e:
            logger.error(f"爬取页面失败: {page_url}, 错误: {e}")
            return [], 0

    # ====================== 查询方法 ======================
    def get_recent_news(self, hours: int = 24, limit: int = 50) -> List[Dict]:
        """
        获取最近N小时的新闻
        :param hours: 时间范围（小时）
        :param limit: 最大返回数量
        :return: 新闻列表
        """
        with get_session_context() as session:
            threshold = datetime.now() - timedelta(hours=hours)
            news_list = session.query(MarketNews).filter(
                MarketNews.publish_time >= threshold
            ).order_by(MarketNews.publish_time.desc()).limit(limit).all()
            
            return [
                {
                    "id": n.id,
                    "news_type": n.news_type,
                    "publish_time": n.publish_time.strftime('%Y-%m-%d %H:%M'),
                    "title": n.title,
                    "content": n.content[:500] if n.content else None,
                    "source": n.source
                }
                for n in news_list
            ]