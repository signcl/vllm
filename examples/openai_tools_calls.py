"""
Inspired by the OpenAI example found here:
    https://platform.openai.com/docs/guides/function-calling/parallel-function-calling
"""

from openai import OpenAI
import datetime
import json

client = OpenAI(api_key="EMPTY", base_url="http://localhost:8000/v1")
models = client.models.list()
model = models.data[0].id
temperature = 0.1
stream = True

EXTRA_BODY_OPENAI = {"stop_token_ids": [32000]}

# Can be used to reset the tokenizer and functions templates. Vllm have to be launch with --privileged argument:
# import httpx
# httpx.get('http://localhost:8000/privileged')


def get_current_date_utc():
    print("Calling get_current_date_utc client side.")
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "The current UTC datetime is (day: %A, date (day/month/year): %d/%m/%Y, time: %H:%M)."
    )


# Example dummy function hard coded to return the same weather
# In production, this could be your backend API or an external API
def get_current_weather(location, unit="celsius"):
    """Get the current weather in a given location"""
    if unit is None:
        unit = "celsius"
    print("Calling get_current_weather client side : (\"%s\", %s)" %
          (str(location), unit))
    if isinstance(location, str):
        if "tokyo" in location.lower():
            temperature = "50" if unit.lower() == "fahrenheit" else "10"
            return json.dumps({
                "location": "Tokyo",
                "temperature": temperature,
                "unit": unit
            })
        elif "san francisco" in location.lower():
            temperature = "75" if unit.lower() == "fahrenheit" else "24"
            return json.dumps({
                "location": "San Francisco",
                "temperature": temperature,
                "unit": unit
            })
        elif "paris" in location.lower():
            temperature = "72" if unit.lower() == "fahrenheit" else "22"
            return json.dumps({
                "location": "Paris",
                "temperature": temperature,
                "unit": unit
            })
    return json.dumps({"location": str(location), "temperature": "unknown"})


def run_conversation(question: str, tool_choice_param):
    # Step 1: send the conversation and available functions to the model
    # messages = [{"role": "user", "content": "What's the weather like in San Francisco, Tokyo, and Paris?"}]
    messages = [{"role": "user", "content": question}]
    tools = [{
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type":
                        "string",
                        "description":
                        "The city and state, e.g. San Francisco, CA as a string",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"]
                    },
                },
                "required": ["location"],
            },
        },
    }, {
        "type": "function",
        "function": {
            "name": "get_current_date_utc",
            "description": "Get the current UTC time",
        },
    }]
    response = client.chat.completions.create(model=model,
                                              messages=messages,
                                              tools=tools,
                                              stream=stream,
                                              tool_choice=tool_choice_param,
                                              temperature=temperature,
                                              extra_body=EXTRA_BODY_OPENAI)
    response_message = ""
    tool_calls = []
    if stream:
        text_message = ""
        for chunk in response:
            if chunk.choices[0].finish_reason is not None:
                if chunk.choices[0].finish_reason == "tool_calls":
                    tool_calls += chunk.choices[0].delta.tool_calls
                    # print("TEST : %s" % chunk.choices[0].delta.tool_calls)
                break
            if chunk.choices[0].delta.content is not None:
                text_message += chunk.choices[0].delta.content
        response_message = {
            "role": "assistant",
            "content": text_message,
            "tool_calls": tool_calls
        }
        # print(str(response_message))
    else:
        if not len(response.choices):
            return None
        response_message = response.choices[0].message
        if response_message.tool_calls is not None:
            tool_calls = response_message.tool_calls
        else:
            print("The tool_calls response is null ?!")

    # Step 2: check if the model wanted to call a function
    if len(tool_calls):
        # Step 3: call the function
        # Note: the JSON response may not always be valid; be sure to handle errors
        available_functions = {
            "get_current_weather": get_current_weather,
            "get_current_date_utc": get_current_date_utc,
        }
        messages.append(
            response_message)  # extend conversation with assistant's reply
        # Step 4: send the info for each function call and function response to the model
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            if function_name in available_functions:
                function_to_call = available_functions[function_name]
                if function_name == "get_current_weather":
                    function_args = json.loads(tool_call.function.arguments)
                    function_response = function_to_call(
                        location=function_args.get("location"),
                        unit=function_args.get("unit"),
                    )
                else:
                    function_response = function_to_call()
            else:
                print("The model halucinated a function : %s" % function_name)

            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": function_response,
            })  # extend conversation with function response
        second_response = client.chat.completions.create(
            model=model, messages=messages, extra_body=EXTRA_BODY_OPENAI
        )  # get a new response from the model where it can see the function response

        for it_msg, msg in enumerate(messages):
            print("Message %i:\n    %s\n" % (it_msg, str(msg)))

        return second_response


print("#############################################################")
question = "What's the weather like in San Francisco, Tokyo, and Paris ? We also need to know the current date."
print("New request using templates: %s" % question)
auto_result = run_conversation(
    question=question,
    tool_choice_param="auto")
print("Final response (tool_choice=\"auto\"):\n%s" % auto_result)
print("#############################################################\n")

print("#############################################################")
question = "What's the weather like in Paris ?"
print("New request using guided generation: %s" % question)
guided_result = run_conversation(question=question,
                                 tool_choice_param={
                                     "type": "function",
                                     "function": {
                                         "name": "get_current_weather"
                                     }
                                 })
print("Final response (tool_choice=\"get_current_weather\"):\n%s" %
      guided_result)
print("#############################################################\n")