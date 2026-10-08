"""Application-owned domain services composed from explicit infrastructure dependencies."""
from app.models.blackjack import BlackjackService
from app.models.daily_spinner import DailySpinnerService
from app.models.invitation import InvitationService
from app.models.member import MemberRepository
from app.models.prediction import PredictionService
from app.models.shard_grant import ShardGrantService
from app.models.star_shard import ShardTransferService
from app.services.admin_reader import DatabaseReader, LogReader
from app.services.oauth import OAuthService


class ApplicationServices:
    """Compose domain services once per application, without retaining live transactions.
    每個應用程式各自持有服務物件，交易僅由單次操作建立與關閉。
    """

    def __init__(self, db, config):
        """Build domain services from the application's database and configuration.
        使用此應用程式的資料庫與設定組合領域服務。

        Args:
            db: 此應用程式獨立的 SQLManager。
            config: 已完成覆寫的 Flask 設定對照表。

        Returns:
            None: 初始化供 API 使用的服務物件。

        Example:
            >>> services = ApplicationServices(db, app.config)
            >>> result = services.members.get_member(user_id)
        """
        self.config = config
        self.members = MemberRepository(db)
        self.shards = ShardTransferService(db)
        self.grants = ShardGrantService(db)
        self.spinner = DailySpinnerService(db)
        self.blackjack = BlackjackService(db)
        self.predictions = PredictionService(db)
        self.invitations = InvitationService(db)
        self.database = DatabaseReader(db)
        self.oauth = OAuthService(config)

    @property
    def logs(self):
        """Create a log reader from the current application settings.
        依目前設定建立日誌讀取物件，讓設定更新仍能立即生效。

        Args:
            None: 使用初始化時注入的設定對照表。

        Returns:
            LogReader: 使用目前目錄與簽章密鑰的快照讀取物件。

        Example:
            >>> page = services.logs.log_page()
        """
        return LogReader(self.config['LOG_DIRECTORY'], self.config['SECRET_KEY'])
