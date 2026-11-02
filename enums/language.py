from enum import Enum


class Language(str, Enum):
    EN = "en"
    FA = "fa"
    FR = "fr"
    DE = "de"
    IT = "it"
    ZH = "zh"

    @staticmethod
    def from_locale(locale: str | None) -> 'Language':
        """Parse BCP-47 tags, defaulting to Persian for an Iranian shop."""
        code = (locale or "").replace("_", "-").split("-", 1)[0].lower()
        try:
            return Language(code)
        except ValueError:
            return Language.FA

    def get_country_code(self):
        match self:
            case Language.EN:
                return "US"
            case Language.FA:
                return "IR"
            case Language.ZH:
                return "CN"
            case _:
                return self.name

    def get_flag_emoji(self):
        if len(self) != 2:
            return "❓"
        regional_A = 0x1F1E6
        flag_chars = []
        for char in self.get_country_code():
            if 'A' <= char <= 'Z':
                flag_char = chr(regional_A + ord(char) - ord('A'))
                flag_chars.append(flag_char)
            else:
                return "❓"
        return ''.join(flag_chars)
