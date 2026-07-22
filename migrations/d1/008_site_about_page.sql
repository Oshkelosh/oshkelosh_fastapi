-- Built-in about page fields on site settings (existing DBs).
-- Fresh installs get the columns from SQLModel create_all.

ALTER TABLE site_settings ADD COLUMN about_page_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE site_settings ADD COLUMN about_page_title VARCHAR(255) NOT NULL DEFAULT 'About';
ALTER TABLE site_settings ADD COLUMN about_page_body TEXT;
ALTER TABLE site_settings ADD COLUMN about_contact_body TEXT;
