import unittest

from agora_automation import _long_form_ok


class AutomatedAgoraQualityTests(unittest.TestCase):
    def test_four_compound_sentences_and_minimum_length_pass(self):
        text = (
            "A politikai intézmények működését a hatalmi viszonyok felől értelmezi, mert a válságok idején "
            "különösen láthatóvá válik, hogy a szabályok mennyire korlátozzák a vezetőket. "
            "A közösség biztonsága nem pusztán a döntéshozók szándékától függ, hanem attól is, "
            "hogy az intézmények képesek-e ellenőrizni egymást. "
            "Amikor a felelősségi körök világosak, a hibák feltárása gyorsabbá válik, "
            "és a közbizalom is könnyebben helyreáll. "
            "Ezért a történelmi tanulság az, hogy a rend tartósságát nem az erő, "
            "hanem az elszámoltatható intézményrendszer biztosítja."
        )
        self.assertTrue(_long_form_ok(text))

    def test_short_commentary_is_rejected(self):
        self.assertFalse(_long_form_ok("A történelmi tanulság fontos, mert a döntések következményekkel járnak."))


if __name__ == "__main__":
    unittest.main()
