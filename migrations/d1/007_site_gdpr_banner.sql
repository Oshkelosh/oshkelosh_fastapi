-- GDPR banner + built-in privacy policy fields on site settings (existing DBs).
-- Fresh installs get the columns from SQLModel create_all.

ALTER TABLE site_settings ADD COLUMN gdpr_banner_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE site_settings ADD COLUMN gdpr_banner_text TEXT;
ALTER TABLE site_settings ADD COLUMN privacy_policy_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE site_settings ADD COLUMN privacy_policy_title VARCHAR(255) NOT NULL DEFAULT 'Privacy Policy';
ALTER TABLE site_settings ADD COLUMN privacy_policy_body TEXT;
ALTER TABLE site_settings ADD COLUMN privacy_policy_effective_date VARCHAR(10);
