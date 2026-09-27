-- Cookie consent mode on site settings (existing DBs).
-- Fresh installs get the column from SQLModel create_all.
-- Shops that already showed the GDPR notice migrate to mode "notice".

ALTER TABLE site_settings ADD COLUMN cookie_consent_mode VARCHAR(16) NOT NULL DEFAULT 'off';

UPDATE site_settings
SET cookie_consent_mode = 'notice'
WHERE gdpr_banner_enabled = 1;
