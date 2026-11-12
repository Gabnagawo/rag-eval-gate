# Assertions

## Introduction

Playwright includes web-specific assertions that automatically retry until the expected condition is met.  Consider the following example:

```python
expect(page.get_by_test_id("status")).to_have_text("Submitted")
```

Playwright will re-test the element with the test ID of `status` until it has the `"Submitted"` text.  It will re-fetch the element and check it repeatedly until the condition is met or the timeout is reached.

By default, the timeout for assertions is 5 seconds.

## Auto-retrying assertions

The following assertions will retry until the assertion passes or the assertion timeout is reached.

| Assertion | Description |
| :- | :- |
| `locator_assertions.to_be_attached` | Element is attached |
| `locator_assertions.to_be_checked` | Checkbox is checked |
| `locator_assertions.to_be_disabled` | Element is disabled |
| `locator_assertions.to_be_editable` | Element is editable |
| `locator_assertions.to_be_empty` | Container is empty |
| `locator_assertions.to_be_enabled` | Element is enabled |
| `locator_assertions.to_be_focused` | Element is focused |
| `locator_assertions.to_be_hidden` | Element is not visible |
| `locator_assertions.to_be_in_viewport` | Element intersects viewport |
| `locator_assertions.to_be_visible` | Element is visible |
| `locator_assertions.to_contain_class` | Element has specified CSS classes |
| `locator_assertions.to_contain_text` | Element contains text |
| `locator_assertions.to_have_accessible_description` | Element has a matching [accessible description](https://w3c.github.io/accname/#dfn-accessible-description) |
| `locator_assertions.to_have_accessible_name` | Element has a matching [accessible name](https://w3c.github.io/accname/#dfn-accessible-name) |
| `locator_assertions.to_have_attribute` | Element has a DOM attribute |
| `locator_assertions.to_have_class` | Element has a class property |
| `locator_assertions.to_have_count` | List has exact number of children |
| `locator_assertions.to_have_c_s_s` | Element has CSS property |
| `locator_assertions.to_have_id` | Element has an ID |
| `locator_assertions.to_have_j_s_property` | Element has a JavaScript property |
| `locator_assertions.to_have_role` | Element has a specific [ARIA role](https://www.w3.org/TR/wai-aria-1.2/#roles) |
| `locator_assertions.to_have_text` | Element matches text |
| `locator_assertions.to_have_value` | Input has a value |
| `locator_assertions.to_have_values` | Select has options selected |
| `locator_assertions.to_match_aria_snapshot` | Element matches provided Aria snapshot |
| `page_assertions.to_have_title` | Page has a title |
| `page_assertions.to_have_u_r_l` | Page has a URL |
| `a_p_i_response_assertions.to_be_o_k` | Response has an OK status |

## Soft assertions

By default, failed assertion will terminate test execution. Playwright also
supports *soft assertions*: failed soft assertions **do not** terminate test
execution, but mark the test as failed.

```python
# Make a few checks that will not stop the test when failed...
expect.soft(page.get_by_test_id("status")).to_have_text("Success")
expect.soft(page.get_by_test_id("eta")).to_have_text("1 day")

# ... and continue the test to check more things.
page.get_by_role("link", name="next page").click()
expect.soft(page.get_by_role("heading", name="Make another order")).to_be_visible()
```

Note that soft assertions only work with the
[`pytest-playwright`](https://pypi.org/project/pytest-playwright/) (or
[`pytest-playwright-asyncio`](https://pypi.org/project/pytest-playwright-asyncio/))
plugin, version `0.8.0` or newer.

## Custom Expect Message

You can specify a custom expect message as a second argument to the `expect` function, for example:

```python
expect(page.get_by_text("Name"), "should be logged in").to_be_visible()
```

When expect fails, the error would look like this:

```bash
    def test_foobar(page: Page) -> None:
>       expect(page.get_by_text("Name"), "should be logged in").to_be_visible()
E       AssertionError: should be logged in
E       Actual value: None
E       Call log:
E       LocatorAssertions.to_be_visible with timeout 5000ms
E       waiting for get_by_text("Name")
E       waiting for get_by_text("Name")

tests/test_foobar.py:22: AssertionError
```

```bash
Microsoft.Playwright.PlaywrightAssertionException : should be logged in

Locator expected to be visible
Call log:
- Expect "ToBeVisibleAsync" with timeout 5000ms
- waiting for GetByText("Name")
```

## Setting a custom timeout

You can specify a custom timeout for assertions either globally or per assertion. The default timeout is 5 seconds.

### Global timeout

```python
from playwright.sync_api import expect

expect.set_options(timeout=10_000)
```

### Per assertion timeout

```python
from playwright.sync_api import expect


def test_foobar(page: Page) -> None:
    expect(page.get_by_text("Name")).to_be_visible(timeout=10_000)
```
