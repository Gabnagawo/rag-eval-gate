# Emulation

## Introduction

With Playwright you can test your app on any browser as well as emulate a real device such as a mobile phone or tablet. Simply configure the devices you would like to emulate and Playwright will simulate the browser behavior such as `"userAgent"`, `"screenSize"`, `"viewport"` and if it `"hasTouch"` enabled. You can also emulate the `"geolocation"`, `"locale"` and `"timezone"` for all tests or for a specific test as well as set the `"permissions"` to show notifications or change the `"colorScheme"`.

## Devices

Playwright comes with a [registry of device parameters](https://github.com/microsoft/playwright/blob/main/packages/isomorphic/deviceDescriptorsSource.json) using `playwright.devices` for selected desktop, tablet and mobile devices. It can be used to simulate browser behavior for a specific device such as user agent, screen size, viewport and if it has touch enabled. All tests will run with the specified device parameters.

```python
from playwright.sync_api import sync_playwright, Playwright

def run(playwright: Playwright):
    iphone_13 = playwright.devices['iPhone 13']
    browser = playwright.webkit.launch(headless=False)
    context = browser.new_context(
        **iphone_13,
    )

with sync_playwright() as playwright:
    run(playwright)
```

<img height="1582" width="916" alt="playwright.dev website emulated for iPhone 13" src="https://user-images.githubusercontent.com/13063165/220411073-76fe59f9-9a2d-463d-8e30-c19a7deca133.png" />

**Note**: Pre-configured devices assume a specific platform. For example, "Desktop Chrome" will provide a Windows-specific user agent string.

If you would like to use the user agent specific to the platform that is running the tests, we recommend unsetting the user agent property.

```python
desktop_chrome = playwright.devices["Desktop Chrome"]
context = browser.new_context(**desktop_chrome, user_agent=None)
```

## Viewport

The viewport is included in the device but you can override it for some tests with `page.set_viewport_size`.

Test file:

The same works inside a test file.

```python
# Create context with given viewport
context = browser.new_context(
  viewport={ 'width': 1280, 'height': 1024 }
)

# Resize viewport for individual page
page.set_viewport_size({"width": 1600, "height": 1200})

# Emulate high-DPI
context = browser.new_context(
  viewport={ 'width': 2560, 'height': 1440 },
  device_scale_factor=2,
)
```

## isMobile

Whether the meta viewport tag is taken into account and touch events are enabled.

```python
context = browser.new_context(
  is_mobile=False
)
```

## Locale & Timezone

Emulate the browser Locale and Timezone which can be set globally for all tests in the config and then overridden for particular tests.

```python
context = browser.new_context(
  locale='de-DE',
  timezone_id='Europe/Berlin',
)
```

<img height="1824" width="2788" alt="Bing in german lang and timezone" src="https://user-images.githubusercontent.com/13063165/220416571-ccc96ab1-44bb-4579-8430-64502fc24a15.png" />

######

Note that this only affects the browser timezone and locale, not the test runner timezone.
To set the test runner timezone, you can use the [`TZ` environment variable](https://nodejs.org/api/cli.html#tz).

## Permissions

Allow app to show system notifications.

```python
context = browser.new_context(
  permissions=['notifications'],
)
```

Allow notifications for a specific domain.

```python
context.grant_permissions(['notifications'], origin='https://skype.com')
```

Revoke all permissions with `browser_context.clear_permissions`.

```python
context.clear_permissions()
```

## Geolocation

Grant `"geolocation"` permissions and set geolocation to a specific area.

```python
context = browser.new_context(
  geolocation={"longitude": 41.890221, "latitude": 12.492348},
  permissions=["geolocation"]
)
```

<img height="1824" width="2788" alt="geolocation for italy on bing maps" src="https://user-images.githubusercontent.com/13063165/220417670-bb22d815-f5cd-47c4-8562-0b88165eac27.png" />

Change the location later:

```python
context.set_geolocation({"longitude": 48.858455, "latitude": 2.294474})
```

**Note** you can only change geolocation for all pages in the context.
## Color Scheme and Media

Emulate the users `"colorScheme"`. Supported values are 'light', 'dark', and 'no-preference'. You can also emulate the media type with `page.emulate_media`.

```python
# Create context with dark mode
context = browser.new_context(
  color_scheme='dark' # or 'light'
)

# Create page with dark mode
page = browser.new_page(
  color_scheme='dark' # or 'light'
)

# Change color scheme for the page
page.emulate_media(color_scheme='dark')

# Change media for page
page.emulate_media(media='print')
```

<img height="1824" width="2788" alt="playwright web in dark mode" src="https://user-images.githubusercontent.com/13063165/220411638-55d2b051-4678-4da7-9f0b-ed22f5a3c47c.png" />

The `"reducedMotion"`, `"forcedColors"` and `"contrast"` options emulate the `prefers-reduced-motion`, `forced-colors` and `prefers-contrast` media features the same way. Supported values are `'reduce'` and `'no-preference'` for reduced motion, `'active'` and `'none'` for forced colors, and `'more'` and `'no-preference'` for contrast. `page.emulate_media` changes them for a single page.

```python
# Create context with reduced motion, forced colors and more contrast
context = browser.new_context(
  reduced_motion='reduce', # or 'no-preference'
  forced_colors='active', # or 'none'
  contrast='more' # or 'no-preference'
)

# Change the media features for the page
page.emulate_media(reduced_motion='reduce', forced_colors='active', contrast='more')
```

## User Agent

The User Agent is included in the device and therefore you  will rarely need to change it however if you do need to test a different user agent you can override it with the `userAgent` property.

```python
context = browser.new_context(
  user_agent='My user agent'
)
```

## Offline

Emulate the network being offline.

```python
context = browser.new_context(
  offline=True
)
```

:::note
Offline emulation affects HTTP requests, such as page navigations, `fetch()` and `XMLHttpRequest`.

WebSocket behavior depends on the browser and whether the connection is already established. Chromium and Firefox fail new WebSocket connections while offline, but do not close already-open connections. Chromium can defer incoming messages until the context goes back online, rather than lose them; Firefox can continue delivering messages while offline. WebKit can allow both new WebSocket connections and traffic on established connections while offline. Do not rely on offline emulation to test WebSocket message loss or connection closure.

Offline emulation does not affect WebRTC traffic: established `RTCPeerConnection`s keep sending and receiving media over UDP. To test WebRTC connection loss, interrupt the connection outside the browser, for example by stopping the TURN server or using an OS-level firewall.
:::

## JavaScript Enabled

Emulate a user scenario where JavaScript is disabled.

```python
context = browser.new_context(
  java_script_enabled=False
)
```
