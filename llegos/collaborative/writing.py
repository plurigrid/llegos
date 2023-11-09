import asyncio
import json
from pprint import pprint
from textwrap import dedent

from dotenv import load_dotenv

from llegos.collaborative.contract_net import (
    Accept,
    CallForProposal,
    Cancel,
    ContractNet,
    ContractorActor,
    Inform,
    ManagerActor,
    Message,
    Propose,
    Reject,
    Request,
)
from llegos.cursive import use_actor_message_fns, use_messages, use_reply_to_fns


class InvariantError(TypeError):
    ...


class Manager(ManagerActor):
    def request(self, message: Request):
        messages = use_messages(
            system=f"{self.state.system}",
            context=message,
            context_history=8,
            prompt="""\
            First, think quietly about what the first task should be.
            Then, think quietly about which contractor is best suited for it.
            Finally, issue the task to that contractor.
            Make the decision, do not seek approval.
            The generated JSON MUST BE in the function_call key, not the content.
            """,
        )

        functions = use_actor_message_fns(
            self.receivers(CallForProposal),
            messages={CallForProposal},
            sender=self,
            parent=message,
        )

        answer: CallForProposal = self.llm.ask(messages=messages, functions=functions)
        return answer.function_result

    def propose(self, message: Propose) -> Reject | CallForProposal | Accept:
        messages = use_messages(
            system=f"""\
            {self.state.system}
            """,
            context=message,
            context_history=4,
            prompt="""\
            First, review the proposed plan and analyze it.
            If you are satisfied with the plan, Accept the plan.
            If you think the plan can be improved, Call for a Proposal.
            If you are not satisfied with the plan, Reject the plan.
            Make the decision, do not seek approval.
            The generated JSON MUST BE in the function_call key, not the content.
            """,
        )

        functions = use_reply_to_fns(
            message,
            {Accept, CallForProposal, Reject},
        )

        answer = self.llm.ask(messages=messages, functions=functions)

        message: Accept | CallForProposal | Reject = answer.function_result
        return message

    def inform(self, message: Inform):
        return Inform.forward(message, to=self.env)

    def reject(self, message: Reject):
        ...

    def cancel(self, message: Cancel):
        ...


class Writer(ContractorActor):
    def call_for_proposal(self, message: CallForProposal) -> Propose | Reject:
        model_kwargs = use_messages(
            model="gpt-4-0613",
            max_tokens=4096,
            system=f"""\
            {self.state.system}

            YOU MUST THINK QUIETLY.
            """,
            context=message,
            context_history=8,
            prompt="""\
            First, think quietly about a plan to complete the task.
            Then, think quietly whether your plan is a good plan.
            If it is a good plan, Propose the plan.
            Otherwise, Reject the task and explain why.
            """,
        )

        function_kwargs, function_call = use_reply_to_fns(
            message,
            {Propose, Reject},
        )

        completion = openai.ChatCompletion.create(**model_kwargs, **function_kwargs)

        return function_call(completion)

    def accept(self, message: Accept) -> Inform | Cancel:
        model_kwargs = use_messages(
            model="gpt-4-0613",
            max_tokens=4096,
            system=self.state.system,
            context=message,
            context_history=8,
            prompt=f"Imagine {self.id} informing {message.sender_id} with generated content.",
        )

        function_kwargs, function_call = use_reply_to_fns(
            message,
            {Inform, Cancel},
        )

        completion = self.cognition.language(**model_kwargs, **function_kwargs)

        reply: Inform | Cancel = function_call(completion)
        return reply

    def reject(self, message: Reject):
        ...


class WritingAgency(ContractNet):
    def request(self, message: Request):
        return Request.forward(message, to=self.manager)


if __name__ == "__main__":
    load_dotenv()
    cognition = SimpleGPTAgent()

    network = WritingAgency(
        system="Writing Agency",
        manager=Manager(
            cognition=cognition,
            system="Writing manager",
        ),
        contractors=[
            # one of these contractors will ultimately do this task
            Writer(
                cognition=cognition,
                system="""\
                    You are engaging and great at explaining things
                    in an understandable way by the general population.
                    """,
            ),
            Writer(
                cognition=cognition,
                system="""\
                    You are an expert in computer science and programming,
                    able to explain technical concepts concisely and precisely.
                    """,
            ),
        ],
    )

    async def run(message: Message):
        async for m in network.send(Propagate(message=message)):
            pprint(json.loads(str(m)))
            print("\n\n")

    request = Request(
        receiver=network,
        objective=dedent(
            """\
                Write a piece comparing the message-passing of biological cells
                to message-passing in multi-agent networks.
                """
        ),
        requirements=[
            "Engaging",
            "Intuitive",
            "Concise",
            "Precise",
        ],
    )

    asyncio.run(run(request))