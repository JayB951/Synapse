import unittest

from artifact_crypto import decrypt_bytes, encrypt_bytes


class ArtifactCryptoTests(unittest.TestCase):
    def test_encrypted_artifact_round_trip(self):
        original = b"WORLD SHARDS private daily edition archive"
        encrypted = encrypt_bytes(original, "test-secret-key")
        self.assertNotEqual(encrypted, original)
        self.assertEqual(decrypt_bytes(encrypted, "test-secret-key"), original)

    def test_wrong_key_fails_closed(self):
        encrypted = encrypt_bytes(b"private sqlite cache", "correct-secret")
        with self.assertRaises(RuntimeError):
            decrypt_bytes(encrypted, "wrong-secret")


if __name__ == "__main__":
    unittest.main()
