import astrbot.api.star as star
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.star_manager import PluginManager
from astrbot.core import DEMO_MODE, logger


class PluginCommands:
    def __init__(self, context: star.Context):
        self.context = context

    async def plugin_ls(self, event: AstrMessageEvent):
        """获取已经安装的插件列表。"""
        plugin_list_info = "已加载的插件：\n"
        for plugin in self.context.get_all_stars():
            plugin_list_info += f"- `{plugin.name}` By {plugin.author}: {plugin.desc}"
            if not plugin.activated:
                plugin_list_info += " (未启用)"
            plugin_list_info += "\n"
        if plugin_list_info.strip() == "":
            plugin_list_info = "没有加载任何插件。"

        plugin_list_info += "\n使用 /plugin help <插件名> 查看插件帮助和加载的指令。\n使用 /plugin on/off <插件名> 启用或者禁用插件。"
        event.set_result(
            MessageEventResult().message(f"{plugin_list_info}").use_t2i(False)
        )

    async def plugin_off(self, event: AstrMessageEvent, plugin_name: str = ""):
        """禁用插件"""
        if DEMO_MODE:
            event.set_result(MessageEventResult().message("演示模式下无法禁用插件。"))
            return
        if not plugin_name:
            event.set_result(
                MessageEventResult().message("/plugin off <插件名> 禁用插件。")
            )
            return
        await self.context._star_manager.turn_off_plugin(plugin_name)  # type: ignore
        event.set_result(MessageEventResult().message(f"插件 {plugin_name} 已禁用。"))

    async def plugin_on(self, event: AstrMessageEvent, plugin_name: str = ""):
        """启用插件"""
        if DEMO_MODE:
            event.set_result(MessageEventResult().message("演示模式下无法启用插件。"))
            return
        if not plugin_name:
            event.set_result(
                MessageEventResult().message("/plugin on <插件名> 启用插件。")
            )
            return
        await self.context._star_manager.turn_on_plugin(plugin_name)  # type: ignore
        event.set_result(MessageEventResult().message(f"插件 {plugin_name} 已启用。"))

    async def plugin_get(self, event: AstrMessageEvent, plugin_repo: str = ""):
        """安装插件"""
        if DEMO_MODE:
            event.set_result(MessageEventResult().message("演示模式下无法安装插件。"))
            return
        if not plugin_repo:
            event.set_result(
                MessageEventResult().message("/plugin get <插件仓库地址> 安装插件")
            )
            return
        logger.info(f"准备从 {plugin_repo} 安装插件。")
        if self.context._star_manager:
            star_mgr: PluginManager = self.context._star_manager
            try:
                await star_mgr.install_plugin(plugin_repo)  # type: ignore
                event.set_result(MessageEventResult().message("安装插件成功。"))
            except Exception as e:
                logger.error(f"安装插件失败: {e}")
                event.set_result(MessageEventResult().message(f"安装插件失败: {e}"))
                return

    async def plugin_help(self, event: AstrMessageEvent, plugin_name: str = ""):
        """获取插件帮助"""
        if not plugin_name:
            event.set_result(
                MessageEventResult().message("/plugin help <插件名> 查看插件信息。")
            )
            return
        plugin = self.context.get_registered_star(plugin_name)
        if plugin is None:
            event.set_result(MessageEventResult().message("未找到此插件。"))
            return
        help_msg = ""
        help_msg += f"\n\n✨ 作者: {plugin.author}\n✨ 版本: {plugin.version}"
        command_handlers = []
        command_names = []
        for handler in star_handlers_registry:
            assert isinstance(handler, StarHandlerMetadata)
            if handler.handler_module_path != plugin.module_path:
                continue
            for filter_ in handler.event_filters:
                if isinstance(filter_, CommandFilter):
                    command_handlers.append(handler)
                    command_names.append(filter_.command_name)
                    break
                elif isinstance(filter_, CommandGroupFilter):
                    command_handlers.append(handler)
                    command_names.append(filter_.group_name)

        if len(command_handlers) > 0:
            help_msg += "\n\n🔧 指令列表：\n"
            for i in range(len(command_handlers)):
                help_msg += f"- {command_names[i]}"
                if command_handlers[i].desc:
                    help_msg += f": {command_handlers[i].desc}"
                help_msg += "\n"

            help_msg += "\nTip: 指令的触发需要添加唤醒前缀，默认为 /。"

        ret = f"🧩 插件 {plugin_name} 帮助信息：\n" + help_msg
        ret += "更多帮助信息请查看插件仓库 README。"
        event.set_result(MessageEventResult().message(ret).use_t2i(False))
